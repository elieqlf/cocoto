"""Calibrage : capture l'écran du jeu avec le moteur choisi, cherche des templates et dessine les zones
de layout.py sur l'image (pour ajuster layout.json si ton jeu s'affiche différemment).

    python tools/calibrate.py --backend adb --out capture.png  find_match end return_home
    python tools/calibrate.py --image capture.png attack_button   (sur une capture existante)
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2  # noqa: E402

from cocoto import layout  # noqa: E402
from cocoto.vision import Templates, match_image  # noqa: E402

BOXES = ("BATTLE_BUTTON", "NEXT_BUTTON", "RETURN_HOME", "BUILD_BUTTON", "WALL_LIST_BOX", "RECO_BOX",
         "DAMAGE_BOX", "SURRENDER_BUTTON", "LEAGUE_BONUS_BOX", "PLAYER_NAME_BOX")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("templates", nargs="*")
    ap.add_argument("--image")
    ap.add_argument("--backend", default="screen", choices=("screen", "window", "adb"))
    ap.add_argument("--device", default="")
    ap.add_argument("--out", default="calibration.png")
    args = ap.parse_args()
    if args.image:
        screen = cv2.imread(args.image)
    else:
        from cocoto.backends import make_backend

        class S(dict):
            def get(self, k, d=None):
                return dict.get(self, k, d)

        screen = make_backend(args.backend, S(adb_device=args.device)).grab()
    if screen is None:
        print("capture impossible")
        return 1
    if screen.shape[1] != 1920:
        screen = cv2.resize(screen, (1920, 1080))
    out = screen.copy()
    for name in BOXES:
        x1, y1, x2, y2 = getattr(layout, name)
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 200, 255), 2)
        cv2.putText(out, name, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)
    tpl = Templates()
    for name in args.templates:
        m = match_image(screen, tpl.get(name))
        if m:
            print(f"{name:28s} score {m.score:.3f} centre ({m.x}, {m.y})")
            cv2.rectangle(out, m.box[:2], m.box[2:], (0, 255, 0), 2)
            cv2.putText(out, f"{name} {m.score:.2f}", (m.box[0], m.box[3] + 14), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 255, 0), 1)
        else:
            print(f"{name:28s} template introuvable")
    cv2.imwrite(args.out, out)
    print("image annotée :", os.path.abspath(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
