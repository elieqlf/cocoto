"""Sondes de test : chaque commande lit l'écran actuel du jeu avec les fonctions du bot, affiche le
résultat en JSON et enregistre une capture annotée. Rien n'est cliqué, sauf `tap` et `zoom`.

    python tools/probe.py shot                    capture + zones de layout.py dessinées
    python tools/probe.py templates [noms…]       scores des templates (tous si aucun nom)
    python tools/probe.py village                 bouton Battle, TH/BH, anglais, panneau, réserves, pseudo
    python tools/probe.py scout                   loot disponible (écran de recherche)
    python tools/probe.py army                    barre de l'armée (cartes, compteurs, sorts, héros)
    python tools/probe.py end                     écran de fin : étoiles, loot, bonus de ligue
    python tools/probe.py panel                   lignes du panneau Build : nom, prix, ressource
    python tools/probe.py reco                    popup de déconnexion ?
    python tools/probe.py points SIDE             points de pose d'un côté (top_left…) dessinés
    python tools/probe.py tap X Y                 clic dans le jeu (repère 1920x1080) : teste les entrées
    python tools/probe.py zoom                    dézoom : teste molette / pincement

Options : --backend screen|window|adb (défaut : réglage de Cocoto), --image capture.png (analyse
hors ligne d'une capture), --out dossier (défaut probe_out/)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import cv2  # noqa: E402

from cocoto import layout, vision  # noqa: E402
from cocoto.backends import Backend, make_backend  # noqa: E402
from cocoto.game import Game  # noqa: E402
from cocoto.state import BotState  # noqa: E402
from cocoto.storage import Settings  # noqa: E402

ZONES = ("BATTLE_BUTTON", "BATTLE_BUTTON_BOX", "BUILD_BUTTON", "NEXT_BUTTON", "RETURN_HOME",
         "WALL_LIST_BOX", "FREE_BUILDERS_BOX", "RECO_BOX", "DAMAGE_BOX", "SURRENDER_BUTTON",
         "LEAGUE_BONUS_BOX", "PLAYER_NAME_BOX", "CHAT_BADGE_BOX", "DAILY_TITLE_BOX")


class ImageBackend(Backend):
    name = "image"

    def __init__(self, path):
        img = cv2.imread(path)
        if img is None:
            raise SystemExit(f"image illisible : {path}")
        self.img = cv2.resize(img, (1920, 1080)) if img.shape[:2] != (1080, 1920) else img

    def grab(self):
        return self.img.copy()

    def move(self, *a, **k):
        pass

    def mouse_down(self, *a):
        pass

    def mouse_up(self, *a):
        pass

    def scroll(self, *a):
        pass

    def key(self, *a):
        pass


def rect(img, box, color, text=""):
    x1, y1, x2, y2 = (int(v) for v in box)
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
    if text:
        cv2.putText(img, text, (x1, max(14, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


def cmd_shot(game, screen, out, args):
    for name in ZONES:
        rect(out, getattr(layout, name), (0, 200, 255), name)
    for i, box in enumerate(layout.STAR_BOXES):
        rect(out, box, (255, 255, 0), f"STAR{i + 1}")
    for k, (y1, y2) in layout.AVAILABLE_LOOT_ROWS.items():
        rect(out, (layout.AVAILABLE_LOOT_X[0], y1, layout.AVAILABLE_LOOT_X[1], y2), (0, 255, 0), "scout " + k)
    for k, (y1, y2) in layout.END_LOOT_ROWS.items():
        rect(out, (layout.END_LOOT_X[0], y1, layout.END_LOOT_X[1], y2), (255, 0, 255), "end " + k)
    for s, x in layout.SLOT_POSITIONS.items():
        cv2.circle(out, (x, layout.ARMY_CARD_Y), 6, (0, 0, 255), -1)
        cv2.putText(out, str(s), (x - 5, layout.ARMY_CARD_Y - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    return {"size": list(screen.shape[:2][::-1])}


def cmd_templates(game, screen, out, args):
    names = args.rest or sorted(game.tpl._build_index().keys())
    rows = []
    for name in names:
        m = game.best(name, screen, scales=(0.9, 1.0, 1.1))
        if m:
            rows.append((round(m.score, 3), name, m.x, m.y, game.tpl.threshold(name)))
    rows.sort(reverse=True)
    for score, name, x, y, thr in rows[:15]:
        if score >= thr:
            t = game.tpl.get(name)
            h, w = t.shape[:2]
            rect(out, (x - w // 2, y - h // 2, x + w // 2, y + h // 2), (0, 255, 0), f"{name} {score}")
    return [{"template": n, "score": s, "center": [x, y], "threshold": t, "found": s >= t}
            for s, n, x, y, t in rows[:40]]


def cmd_village(game, screen, out, args):
    from cocoto.features.accounts import read_player_name
    from cocoto.features.village import game_in_english, read_village_resources, storage_fill
    rect(out, layout.BATTLE_BUTTON_BOX, (0, 200, 255), "battle")
    return {"battle_button": bool(game.battle_button_visible(screen)), "village": game.village(screen),
            "english": game_in_english(game, screen), "build_panel_open": bool(game.panel_open(screen)),
            "storage_fill": {k: round(v, 3) for k, v in storage_fill(screen).items()},
            "resources": read_village_resources(screen), "player": read_player_name(game, screen)}


def cmd_scout(game, screen, out, args):
    from cocoto.features.search import read_available_loot
    for k, (y1, y2) in layout.AVAILABLE_LOOT_ROWS.items():
        rect(out, (layout.AVAILABLE_LOOT_X[0], y1, layout.AVAILABLE_LOOT_X[1], y2), (0, 255, 0), k)
    vals = read_available_loot(game, screen)
    return {"gold": vals[0], "elixir": vals[1], "dark": vals[2], "next_button": game.score("end", screen)}


def cmd_army(game, screen, out, args):
    from cocoto.features import attack
    cards = attack.read_army(game, screen)
    for c in cards:
        rect(out, (c.left, layout.ARMY_BAR_Y[0], c.right, layout.ARMY_BAR_Y[1]),
             (255, 0, 255) if c.spell else (0, 255, 0), f"{'S' if c.spell else (c.hero or 'T')} {c.count}")
    return [{"x": c.x, "left": c.left, "right": c.right, "count": c.count, "spell": bool(c.spell),
             "hero": c.hero} for c in cards]


def cmd_heroskin(game, screen, out, args):
    """heroskin X N [nom] : enregistre le portrait de la carte de la barre en X comme template du
    héros N (1 Roi, 2 Reine, 3 Gardien, 4 Champion, 5 Prince, 6 Duc) dans %APPDATA%\\Cocoto\\img."""
    from cocoto import paths
    from cocoto.features import attack
    x, n = int(args.rest[0]), int(args.rest[1])
    tag = args.rest[2] if len(args.rest) > 2 else "skin"
    card = next(((l, r) for l, r in attack.card_edges(screen) if l <= x <= r), None)
    if card is None:
        return {"error": f"aucune carte en x={x}"}
    l, r = card
    box = (l + 4, 970, r - 4, 1026)          # visage : sous le compteur, au-dessus du niveau
    zone, _, _ = vision.crop(screen, box)
    folder = paths.data_path("img")
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, f"hero{n}_{tag}.png")
    cv2.imwrite(dest, zone)
    rect(out, box, (0, 255, 255), f"hero{n}_{tag}")
    return {"saved": dest, "box": box}


def cmd_end(game, screen, out, args):
    import re
    from cocoto import ocr
    from cocoto.features import attack
    for box in layout.STAR_BOXES:
        rect(out, box, (255, 255, 0))
    for k, (y1, y2) in layout.END_LOOT_ROWS.items():
        rect(out, (layout.END_LOOT_X[0], y1, layout.END_LOOT_X[1], y2), (255, 0, 255), k)
    for k, (y1, y2) in layout.LEAGUE_BONUS_ROWS.items():
        rect(out, (layout.LEAGUE_BONUS_X[0], y1, layout.LEAGUE_BONUS_X[1], y2), (0, 200, 255), k)
    bonus = attack.read_league_bonus_rows(screen)
    return {"stars": attack.count_stars(screen), "loot": attack.read_end_loot(screen),
            "league_bonus_template": game.score("league_bonus", screen), "league_bonus_ocr": bonus,
            "return_home": max(game.score("return_home", screen), game.score("return_home1", screen))}


def cmd_panel(game, screen, out, args):
    from cocoto.features.panel import BuildPanel
    p = BuildPanel(game)
    rows = []
    for y, text in p.rows(screen):
        rows.append({"y": y, "text": text, "cost": p.read_cost(screen, y), "resource": p.cost_resource(screen, y),
                     "red": p.cost_is_red(screen, y), "in_progress": p.in_progress(screen, y)})
        rect(out, p.cost_box(y), (0, 255, 0), text[:20])
    return {"panel_open": p.is_open(screen), "free_builders": p.free_builders(screen), "rows": rows}


def cmd_reco(game, screen, out, args):
    from cocoto.features.reconnect import popup_visible, reason
    rect(out, layout.RECO_BOX, (0, 0, 255), "RECO_BOX")
    return {"popup": bool(popup_visible(screen)), "reason": reason(game, screen)}


def cmd_points(game, screen, out, args):
    from cocoto.features import attack
    side = (args.rest or ["top_left"])[0]
    pts = attack.edge_points(side)
    for x, y in pts:
        cv2.circle(out, (x, y), 5, (0, 255, 0), -1)
    for x, y in attack.spell_points(side, 4):
        cv2.circle(out, (x, y), 7, (255, 0, 255), 2)
    return {"side": side, "points": pts,
            "note": "à vérifier APRÈS dézoom + glissement (python tools/probe.py zoom puis capture)"}


def cmd_tap(game, screen, out, args):
    x, y = int(args.rest[0]), int(args.rest[1])
    game.backend.click(x, y)
    cv2.circle(out, (x, y), 12, (0, 0, 255), 3)
    return {"clicked": [x, y], "backend": game.backend.describe()}


def cmd_zoom(game, screen, out, args):
    game.backend.zoom_out(960, 540, 4)
    return {"zoom_out": "envoyé", "backend": game.backend.describe()}


COMMANDS = {n[4:]: f for n, f in globals().items() if n.startswith("cmd_")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--backend", choices=("screen", "window", "adb"))
    ap.add_argument("--image")
    ap.add_argument("--out", default="probe_out")
    args = ap.parse_args()
    layout.load_overrides()
    if args.image:
        backend = ImageBackend(args.image)
    else:
        settings = Settings()
        backend = make_backend(args.backend or settings.get("backend", "screen"), settings)
    game = Game(backend, BotState())
    screen = game.grab(wait=False)
    out = screen.copy()
    result = COMMANDS[args.command](game, screen, out, args)
    os.makedirs(args.out, exist_ok=True)
    stamp = time.strftime("%H%M%S")
    raw = os.path.join(args.out, f"{args.command}_{stamp}_raw.png")
    annotated = os.path.join(args.out, f"{args.command}_{stamp}.png")
    cv2.imwrite(raw, screen)
    cv2.imwrite(annotated, out)
    print(json.dumps({"command": args.command, "result": result, "capture": os.path.abspath(raw),
                      "annotated": os.path.abspath(annotated)}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
