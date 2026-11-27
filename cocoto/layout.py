"""Coordonnées de l'écran du jeu, dans le repère 1920x1080 (jeu en plein écran, Google Play Games).

Valeurs relevées dans les constantes de CoCoBot 0.0.27 (voir docs/ANALYSE.md) ou mesurées sur les
templates. Toutes les zones sont (x1, y1, x2, y2). Elles peuvent être corrigées sans toucher au
code dans <données utilisateur>/layout.json, ex. {"NEXT_BUTTON": [1667, 773, 1891, 867]}.
"""
from __future__ import annotations

import json
import os

W, H = 1920, 1080
SCREEN_CENTER = (960, 540)

# ------------------------------------------------------------------ village
BATTLE_BUTTON = (40, 925, 170, 1045)          # zone cliquée pour « Battle »
BATTLE_BUTTON_BOX = (20, 880, 200, 1060)      # bouton jaune (présence = village affiché)
BATTLE_LABEL_BOX = (35, 1010, 185, 1060)      # mot « Battle » (langue du jeu)
BUILD_LABEL_BOX = (1735, 1010, 1895, 1060)    # mot « Build »
BUILD_BUTTON = (1750, 910, 1880, 1045)        # bouton Build (ouvre la liste des améliorations)
VILLAGE_ICON_BOX = (20, 880, 200, 1060)       # épée (TH) / haches (BH) du bouton Battle
PLAYER_NAME_BOX = (150, 62, 340, 104)         # pseudo en haut à gauche
STORAGE_BARS = {                              # réserves en haut à droite : (y1, y2[, x1, x2]) sous les chiffres
    "gold": (58, 64), "elixir": (120, 126), "dark": (181, 187, 1655, 1846)}   # mesuré GPG 2026-11
STORAGE_BAR_X = (1572, 1846)                  # bord gauche de la barre → début de l'icône
VILLAGE_RES_ROWS = {"gold": (33, 64), "elixir": (95, 126), "dark": (155, 188)}   # mesuré GPG 2026-11
VILLAGE_RES_X = (1600, 1846)
KEEP_ALIVE_TAP = (1580, 38, 1700, 58)          # barre d'or : clic = simple info-bulle (maintien de connexion)
CHAT_BADGE_BOX = (40, 330, 120, 450)          # pastille rouge du bouton du chat
CHAT_OPEN_BUTTON = (40, 400)
CLOSE_VILLAGE_CLICK = (500, 250, 1000, 600)   # clic « dans le vide » pour fermer un panneau (secours)
PANEL_CLOSE_X = (1888, 35)                    # croix rouge du panneau Buildings & Heroes (mesuré)

# ------------------------------------------------------------------ recherche d'adversaire
FIND_MATCH_ZONE = (150, 600, 1000, 900)
NEXT_BUTTON = (1667, 773, 1891, 867)
AVAILABLE_LOOT_X = (78, 330)
AVAILABLE_LOOT_ROWS = {"gold": (118, 158), "elixir": (166, 206), "dark": (214, 254)}

# ------------------------------------------------------------------ combat
MAP_CX = 960
MAP_HALF_W = 819
MAP_HALF_H = 614
MAP_VIEW_CY = {"down": 664, "up": 324}        # centre de la carte après glissement bas / haut
ATTACK_SIDES = ("top_left", "top_right", "bottom_left", "bottom_right")
ATTACK_EDGE_SPAN = {"top": (0.12, 0.88), "bottom": (0.12, 0.85)}
ATTACK_EDGE_N_POINTS = 24
ATTACK_EDGE_INSET = 38
DRAG_DISTANCE = 400
ARMY_BAR_Y = (930, 1065)                      # barre des cartes en bas
ARMY_CARD_Y = 995
UNIT_HEALTH_BAR_Y = (893, 910)                 # barre de vie au-dessus d'un héros / siège posé (mesuré)
SLOT_POSITIONS = {1: 335, 2: 453, 3: 609, 4: 727, 5: 837, 6: 963, 7: 1075, 8: 1221,
                  9: 1339, 10: 1455, 11: 1585, 12: 1700}
DAMAGE_BOX = (1760, 835, 1905, 878)           # « 52% » pendant le combat (mesuré GPG 2026-11)
SURRENDER_BUTTON = (40, 825, 190, 870)
REMAINING_LOOT_X = (78, 330)

# ------------------------------------------------------------------ fin de combat
STAR_BOXES = ((745, 180, 815, 245), (935, 55, 985, 105), (1105, 180, 1175, 245))
STAR_SILVER_RATIO = 0.45
END_LOOT_X = (700, 1003)                      # chiffres à gauche des icônes (mesuré GPG 2026-11)
END_LOOT_ROWS = {"gold": (472, 522), "elixir": (543, 590), "dark": (617, 661)}
# Panneau Battle : deux cartes, chacune avec un « Find a Match » (même template find_match).
# Mesuré GPG 2026-11 : carte Battle x 65-485, carte Ranked x 500-925 (bouton au centre (711, 742)).
RANKED_FIND_MATCH_MIN_X = 490                 # à gauche = combat normal, à droite = Ranked
RANKED_COUNTER_DBOX = (-46, 18, 114, 70)      # compteur « 0/8 » sous le bouton, relatif à son centre
RANKED_LOOT_X = (1330, 1508)
RANKED_LOOT_ROWS = {"gold": (524, 566), "elixir": (579, 621), "dark": (633, 675)}
LEAGUE_BONUS_BOX = (1320, 460, 1610, 525)     # titre « 100% Bonus: »
LEAGUE_BONUS_X = (1345, 1518)                 # « +90000 » à gauche des icônes (mesuré GPG 2026-11)
LEAGUE_BONUS_ROWS = {"gold": (526, 568), "elixir": (581, 623), "dark": (636, 678)}
RETURN_HOME = (843, 880, 1072, 969)

# ------------------------------------------------------------------ murs et améliorations
UPGRADE_PANEL_EDGE_X = (1402, 1404)           # bord gauche noir du panneau ouvert
UPGRADE_PANEL_Y = (150, 950)
WALL_LIST_BOX = (1480, 75, 1760, 955)         # colonne des noms de la liste
WALL_COST_DY = 28                             # le prix est sous le nom (mesuré GPG 2026-11)
PANEL_COST_X2 = 1880                          # fin des chiffres du prix (alignés à droite)
PANEL_COST_ICON_X = (1880, 1910)              # icône de ressource du prix
WALL_SCROLL_POS = (1660, 600)
WALL_SELECTED_TITLE_BOX = (470, 740, 1400, 805)  # « Wall (Level 14) x 2 » au-dessus des boutons (mesuré)
FREE_BUILDERS_BOX = (1430, 1018, 1505, 1055)   # « 1/6 » (mesuré GPG 2026-11)
BH_FREE_BUILDERS_BOX = (1480, 1016, 1590, 1056)
LAB_FREE_BOX = (1555, 1018, 1640, 1055)        # « 1/1 » (mesuré GPG 2026-11)
PANEL_TABS = {"builders": (1467, 1000), "lab": (1597, 1000)}
UPGRADE_FILTER_BUTTON = (1460, 35)
UPGRADE_FILTERS = {"Army": (812, 328, 1020, 400), "Defense": (1042, 328, 1248, 400),
                   "Hero": (1270, 328, 1478, 400), "Resource": (812, 416, 1020, 488)}
UPGRADE_WINDOW_BUTTONS = (300, 740, 1650, 1040)  # rangée des boutons sous un bâtiment sélectionné
UPGRADE_PRICE_BAND = (250, 815, 1400, 935)    # prix au-dessus des boutons Upgrade : y≈830 (une ligne) ou y≈904 (boutons sur deux lignes, vu GPG 2026-11-12)
UPGRADE_ICON_TO_BUTTON = (-48, 48)            # icône du prix → centre du bouton
UPGRADE_WINDOW_GREEN_BOX = (1100, 840, 1560, 1030)  # bouton vert « Upgrade » (prix réduit) de la fenêtre du mur

# ------------------------------------------------------------------ popups
RECO_BOX = (560, 445, 1360, 635)              # cadre de la popup de déconnexion
RECO_SEARCH_BOX = (380, 330, 1540, 750)       # recherche des textes / du bouton (taille variable)
RECO_RELOAD = (640, 606)                      # secours : RELOAD GAME mesuré (fenêtre 1765x993)
DAILY_TITLE_BOX = (760, 35, 1180, 90)
DAILY_CLOSE = (1650, 250)
WELCOME_BOX = (500, 270, 1420, 330)
PICK_REWARD_BOX = (500, 100, 1420, 280)
PICK_REWARD_RIGHT_CARD = (1240, 390, 1460, 750)

# ------------------------------------------------------------------ comptes (Supercell ID)
ACCOUNT_PORTRAIT_BOX = (40, 60, 130, 140)
ACCOUNT_SETTINGS_TAB = (1415, 105, 1530, 150)
ACCOUNT_SWITCH_BOX = (1150, 170, 1330, 300)
ACCOUNT_LIST_BOX = (1515, 480, 1900, 1080)
ACCOUNT_ROW_X = 1650
ACCOUNT_PANEL_CLOSE = (1872, 46)
ACCOUNT_PROFILE_CLOSE = (1620, 122)

# ------------------------------------------------------------------ capitale
CAPITAL_TITLE_BOX = (760, 35, 1180, 90)
RAID_BUTTON_BOX = (1735, 960, 1905, 1055)
RAID_ATTACKS_BADGE = (1820, 975)
RAID_DISTRICTS = ("Capital Peak", "Barbarian Camp", "Wizard Valley", "Balloon Lagoon",
                  "Builder's Workshop", "Dragon Cliffs", "Golem Quarry", "Skeleton Park",
                  "Goblin Mines")

# ------------------------------------------------------------------ base des ouvriers
BH_SLOT_POSITIONS = {1: 465, 2: 591, 3: 717, 4: 843, 5: 970, 6: 1096, 7: 1222, 8: 1348,
                     9: 1475, 10: 1601}
BH_CARD_Y = 965
BH_HERO_CARD = (320, 965)
BH_SWAP_BUTTON = (316, 1022, 372, 1052)
BH_HERO_CARD_BOX = (240, 880, 420, 1080)
BH_ARENAS = {   # côtés de l'arène : (début, fin) du bord
    1: {"left": ((297, 300), (950, 780)), "right": ((1575, 297), (936, -180))},
    2: {"left": ((395, 300), (1042, 746)), "right": ((1690, 300), (1042, -146))},
}
BH_STAR_BOXES = ((732, 304, 782, 354), (943, 231, 993, 281), (1151, 306, 1201, 356))
BH_REWARD_ROWS = {"gold": (645, 698), "elixir": (712, 765)}
BH_REWARD_X = (1080, 1360)
BH_GAUGE_Y = (877, 883)
BH_GAUGE_SEGMENTS = ((279, 299), (306, 326), (333, 353))
BH_LAB_CARDS_X = (429, 640, 850, 1060, 1270, 1481)
BH_LAB_CARDS_Y = (648, 858)

# ------------------------------------------------------------------ chargement des surcharges
_OVERRIDES_LOADED = False


def load_overrides(path: str | None = None) -> list[str]:
    """Applique layout.json (clés MAJUSCULES de ce module). Retourne les clés modifiées."""
    global _OVERRIDES_LOADED
    if path is None:
        from . import paths
        path = paths.data_path("layout.json")
    changed = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        g = globals()
        for k, v in data.items():
            if k.isupper() and k in g:
                g[k] = tuple(v) if isinstance(v, list) else v
                changed.append(k)
    _OVERRIDES_LOADED = True
    return changed
