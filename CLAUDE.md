# Cocoto — passation pour Claude

Lis ce fichier en entier avant de travailler. Il résume une première session (sur macOS) qui a fait
la rétro-ingénierie de **CoCoBot 0.0.27** (bot Clash of Clans payant) et écrit **Cocoto**, une
réimplémentation en code neuf. **Rien n'a encore été testé contre le vrai jeu** : c'est le but de la
session Windows (Google Play Games + Clash of Clans).

## Où est le contexte
- `docs/ANALYSE.md` : comment CoCoBot fonctionne (packaging, moteurs, chaque fonctionnalité, partie
  licence non reproduite) et la correspondance avec les modules de Cocoto. **À lire d'abord.**
- `re_notes/` (local, ignoré par git, régénérable : `python tools/dump_constants.py <CoCoBot.exe>`) :
  - `defs_sorted.txt` : les 981 fonctions/classes de l'original avec paramètres et n° de ligne ;
  - `main_consts.txt` : les 7817 constantes du script, **dans l'ordre du source** (chaînes, docstrings
    en français, nombres = coordonnées et seuils) ; `main_consts_compact.txt` : même chose, compactée ;
  - `docstrings_bot_core.txt` : docstrings des fonctions du cœur du bot (lignes 6500-16200).
  Pour retrouver une coordonnée : chercher le nom de la fonction (`#### DEF read_wall_cost`) puis lire
  les constantes qui suivent. Les valeurs de niveau module (tuples de zones) sont **à la fin** du
  fichier, dans l'ordre de définition, souvent **sans leur nom** (Nuitka déduplique les noms).
- `assets/` (local, ignoré) : templates `img/` et modèle EasyOCR extraits de la copie de l'utilisateur
  (`python tools/extract_assets.py <CoCoBot.exe>`). Ne jamais les publier.

## Faits clés sur l'original (observés)
- Exe Nuitka onefile : en-tête `KAY` + flux zstd ; entrées = nom UTF-16 + uint64 taille + CRC32.
- Script unique `__main__` (~16 300 lignes, Python 3.13), customtkinter, OpenCV, EasyOCR, pyautogui.
- Repère des coordonnées : **1920x1080**, jeu en plein écran. Background mode = PrintWindow +
  PostMessage sur la fenêtre `CROSVM_1`. MuMu = ADB, 1728x1080 DPI 240, image recomposée.
- Seuil template par défaut 0,8 (`TM_CCOEFF_NORMED`) ; boutons « vus 2 fois au même endroit ».

## Carte du code
`cocoto/` : `backends/` (screen, win32, adb) · `vision.py` · `ocr.py` · `layout.py` (toutes les
zones) · `game.py` (façade : grab/find/wait/click) · `features/` (attack, search, village, panel,
walls, upgrades, breaks, reconnect, clan_games, donate, raids, accounts) · `bot_th.py` / `bot_bh.py`
(boucles) · `controller.py` · `notify.py` · `remote.py` · `dashboard.py` · `storage.py` /
`config.py` / `parsing.py` / `validate.py` · `ui/`.
Outils : `tools/probe.py` (sondes sans clic), `tools/calibrate.py`, `tools/extract_assets.py`,
`tools/dump_constants.py`. Tests : `python -m pytest -q` (44 tests, dont un combat simulé).

## Confiance dans `layout.py`
| Niveau | Zones |
|---|---|
| **Observé** (valeur + contexte clair dans le binaire) | `BATTLE_BUTTON`, `NEXT_BUTTON`, `RETURN_HOME`, `BATTLE_LABEL_BOX`, `BUILD_LABEL_BOX`, `VILLAGE_ICON_BOX`, `UPGRADE_PANEL_EDGE_X/Y`, `MAP_HALF_W/H`, `MAP_VIEW_CY`, `ATTACK_EDGE_SPAN`, `DRAG_DISTANCE`, `UPGRADE_FILTERS`, `BH_SLOT_POSITIONS`, `BH_HERO_CARD`, `BH_STAR_BOXES`, `BH_ARENAS`, `RAID_DISTRICTS`, ports/chemins ADB MuMu, `ANCHORED_REGIONS` |
| **Déduit** (valeur du binaire, nom attribué par l'ordre) | `SLOT_POSITIONS`, `STAR_BOXES`, `AVAILABLE_LOOT_*`, `END_LOOT_*`, `RANKED_LOOT_*`, `LEAGUE_BONUS_BOX`, `WALL_LIST_BOX`, `WALL_SCROLL_POS`, `FREE_BUILDERS_BOX`, `LAB_FREE_BOX`, `PANEL_TABS`, `BUILD_BUTTON`, `SURRENDER_BUTTON`, `PICK_REWARD_*`, `RECO_BOX`, `DAILY_*`, `ACCOUNT_*`, `CAPITAL_TITLE_BOX`, `RAID_*`, `BH_GAUGE_*`, `BH_LAB_CARDS_*`, `CLOSE_VILLAGE_CLICK` |
| **Deviné** (aucune preuve, à mesurer en premier) | `STORAGE_BARS`, `STORAGE_BAR_X`, `VILLAGE_RES_*`, `CHAT_BADGE_BOX`, `CHAT_OPEN_BUTTON`, `DAMAGE_BOX`, `ARMY_BAR_Y`, `ARMY_CARD_Y`, `RECO_RELOAD`, `WALL_COST_DY`, `UPGRADE_WINDOW_BUTTONS`, `BH_REWARD_X`, `ATTACK_EDGE_N_POINTS`, `ATTACK_EDGE_INSET` |

Corriger une zone : `%APPDATA%\Cocoto\layout.json` (`{"NOM": [x1, y1, x2, y2]}`) pour tester, puis
reporter la bonne valeur dans `layout.py` une fois confirmée.

## Plan de test sur Windows (dans cet ordre)
Préparer : Google Play Games, Clash of Clans **en anglais**, plein écran, écran 16:9, échelle
Windows 100 %. L'utilisateur met le jeu sur l'écran voulu, Claude lance la sonde et **lit l'image
annotée** (`probe_out/*.png`) pour vérifier/corriger les zones.

1. `python tools/probe.py shot` puis `templates` sur le **village** → bouton Battle, `village_th`.
   `python tools/probe.py village` → `battle_button` true, `village` "TH", `english` true, réserves, pseudo.
2. Mode arrière-plan : `python tools/probe.py shot --backend window` (image non noire, bonne taille),
   puis `tap X Y` sur un endroit sans risque pour vérifier que le clic arrive (sinon : jeu en admin ?).
3. L'utilisateur ouvre Battle → `templates find_match` ; My Army → `templates army_attack cake army_request` ;
   écran de scout → `scout` (loot OCR) + `army` (cartes, compteurs, sorts, héros).
4. Pose : sur le scout, `zoom`, l'utilisateur glisse la vue (ou le bot), `points top_left` → les points
   doivent longer le bord de la zone de pose. Ajuster `MAP_*`, `ATTACK_EDGE_INSET`.
5. Écran de fin → `end` (étoiles, loot, bonus de ligue) ; popup de déconnexion → `reco`.
6. Panneau Build ouvert → `panel` (noms, prix, ressource, ouvriers libres).
7. Vrai START, réglages prudents (loot minimum bas, murs/améliorations off, 1 combat), suivre
   `%APPDATA%\Cocoto\bot_log.txt` et `error_shots\`. Puis activer les fonctions une par une
   (murs, bâtiments, récolte, dons, Jeux de clan, raids, BH, comptes).

Installer EasyOCR (`pip install -r requirements.txt`, torch ≈ 1 Go) avant les sondes OCR.

## Règles du projet
- Python **3.9+** (`from __future__ import annotations`, pas de `match`) ; textes UI/logs en français
  (anglais via `tr(en, fr)`).
- Code et textes **nouveaux** : ne pas recopier le code ni les longs textes de CoCoBot. Pas de
  système de licence, pas d'appel au serveur de l'auteur (`kalashdu13.pythonanywhere.com`).
- Le bot ne lit la config que via `LiveConfig` ; toute attente passe par `state.sleep/check` (STOP et
  reconnexion) ; nouvelle zone d'écran → `layout.py`.
- Après chaque correction : `python -m pytest -q`.

## Journal de calibrage
(À remplir pendant les tests Windows : zone, ancienne valeur, nouvelle valeur, comment vérifiée.)

Session Windows 2026-11-11 — Python 3.12 (venv `.venv`), GPG fenêtré 1323x744 (16:9), jeu en **français**.
- `tools/extract_assets.py` : zstandard 0.25 lève « Unknown frame descriptor » après la trame
  (données de fin de l'exe) → lecture par blocs, arrêt propre. 347 fichiers, 0 CRC faux.
- Backend `window` : capture OK (1920x1080 recomposé), clics OK (Hôtel de ville sélectionné au pixel).
- `village` : `battle_button`, `village_th` (0,89) OK ; `english` false = correct (jeu en FR).
- `VILLAGE_RES_ROWS` gold/elixir/dark : (85,120)/(155,190)/(225,258) → (33,64)/(95,126)/(155,188) ;
  `VILLAGE_RES_X` (1600,1830) → (1600,1846). Vérifié : OCR 7 977 717 / 12 082 587 / 86 586 exacts.
- `STORAGE_BARS` → bande sous les chiffres (58,64)/(120,126)/(181,187), barre noire plus courte
  `x 1655-1846` (4ᵉ/5ᵉ valeurs optionnelles) ; `STORAGE_BAR_X` → (1572,1846). Teintes : or 15-30
  (la partie vide laisse voir la forêt H≈31-41), noir H 120-165 S>100 V>25. Résultat 36 %/60 %/6 %, cohérent à l'œil.
- `PLAYER_NAME_BOX` : OCR « elie Ie bg » pour « élie le bg » (accent + l/I) — à tolérer dans la comparaison.
- Jeu passé en anglais. Panneau Battle = 2 cartes (Battle x 65-485, Ranked x 500-925), chacune avec
  un « Find a Match » qui matche `find_match` (0,94 / 0,95). `ranked_find_match.png` n'existe pas :
  dans l'original c'est une fonction (find_match, gauche masquée par `RANKED_FIND_MATCH_MIN_X`).
  → `RANKED_FIND_MATCH_MIN_X = 490` ; combat normal cherché à gauche seulement (avant : cliquait le
  Ranked !). Compteur « 0/8 » : `RANKED_COUNTER_DBOX = (-46, 18, 114, 70)` sous le bouton (avant :
  deviné 130 px au-dessus), chiffres isolés (V≥180, S≤130) avant OCR → (0, 8).
- My Army : `army_attack` 0,975 ; `army_request` 0,84 (château plein → grisé, non trouvé = correct) ;
  pas de Cake. Le scout démarre la bataille après 30 s : End Battle sans troupe = retour sans perte.
- Scout : `AVAILABLE_LOOT_*` exacts (1 468 427 / 1 596 430 / 12 950), `next_button` 0,98.
- Barre d'armée : fond translucide → cartes trouvées par leurs bords verticaux (`card_edges`,
  largeur 108-111, pas 121 ; troupes x 277/397/519, siège 662, héros 788/909/1029/1151, sorts
  1287/1408/1528). Bandeau : troupe H≈104, sort H≈126 mais cadres héros violets aussi → sort = compteur
  présent + H≥117. « x1 » perdu par EasyOCR → chiffres lus composante par composante (étroite = 1).
- Héros avec skin non reconnus par `heroN.png` → templates perso `%APPDATA%\Cocoto\img\heroN_*.png`
  (`probe.py heroskin X N`) ; enregistrés : hero2_skin (Reine), hero4_skin (Champion). À confirmer
  sur un autre scout.
- Points de pose `top_left` (vue non glissée) : bonne direction, ~60-80 px à l'intérieur de la ligne
  rouge — à refaire après le glissement de vue du bot. Le dézoom n'a rien changé (déjà au max ?).
- Déconnexion « Anyone there? » (popup Android) : `popup_visible` OK mais `reco_inactivity` 0,44
  → le bot ne se serait jamais reconnecté. Le texte ne suit pas la taille de la fenêtre (échelle 1,04
  à 1765x993) → `RECO_SCALES` 0,80-1,40 pas 0,02 (0,82), recherche dans `RECO_SEARCH_BOX`
  (380,330,1540,750), clic sur le bouton RELOAD GAME trouvé (template `afk` 0,90), motif « afk » si
  seul le bouton est reconnu. `RECO_RELOAD` (960,604) → (640,606) en secours. `reload_game` vérifié
  en direct : village revenu.
- Vue après `prepare_view("top_left")` : losange `MAP_*` calé sur la limite herbe/forêt, points le
  long du bord hors de la base → **pose réelle OK** (armée auto lue en direct à l'identique, 11
  cartes vidées, héros avec skin reconnus). Combat : 100 %, 3 étoiles.
- `DAMAGE_BOX` (1700,930,1900,990) → (1760,835,1905,878) : « 52% » lu 52. Loot restant OK.
- Fin : `STAR_BOXES` OK (3), `return_home1` 0,96. `END_LOOT_X` (1003,1330) → (700,1003) (lisait les
  icônes) : 1 256 565 / 1 311 628 / 14 557 exacts. Bonus de ligue : `LEAGUE_BONUS_BOX` = titre seul,
  OCR collé « 10098545 » → lecture par ligne `LEAGUE_BONUS_X` (1345,1518) +
  `LEAGUE_BONUS_ROWS` (526,568)/(581,623)/(636,678), « + » retiré : 90000/90000/950.
- Capacités des héros : désactivées par défaut (réglage), non testées.
- Panneau « Buildings & Heroes » (volet droit x 1405-1920) : `panel_open` OK, `open()` (BUILD_BUTTON)
  et `close()` (CLOSE_VILLAGE_CLICK) vérifiés en direct. Prix sous le nom : `WALL_COST_DY` 34 → 28 ;
  chiffres jusqu'à `PANEL_COST_X2` = 1880 ; icône `PANEL_COST_ICON_X` (1880,1910) : or H≈21,
  élixir H≈140, noir = pixels V<70 (le fond brun H≈12 trompait la teinte). Prix : 50000 / 5000000 /
  1000000 / 6250 / 6000 / 3000 exacts, « 1 000 000 » était lu 0 (1 fin perdu) →
  `ocr.read_digits_mask` (contrôle nb chiffres = nb composantes, repli par composante).
  `FREE_BUILDERS_BOX` (1425,975,1510,1018) → (1430,1018,1505,1055), `LAB_FREE_BOX` →
  (1555,1018,1640,1055) ; EasyOCR perd le « / » → `ocr.read_fraction` (coupe sur la composante
  peu remplie) : 1/6 et 1/1. Noms : rapprochement OK (« clan Castle », « Elixi Collector x 7 ») ;
  pièges et Crafting Station absents de `TH_BUILDINGS` (choix de l'UI, pas lus).
- **Étape 7 — premier vrai START** (Controller, backend window, loot min 100k/100k/0, murs /
  améliorations / récolte / dons / Jeux de clan / Cake / renforts / Ranked off, STOP après 1 combat) :
  budget lu, Battle → Find a Match (carte normale) → Attack!, base 1 passée (29 538 or), base 2
  gardée (1,29 M / 1,24 M), côté bottom_left, armée auto lue à l'identique, posée, 2⭐,
  +1 126 295 or +1 165 341 élixir +11 692 noir, Return Home, village. Aucune erreur, pas d'error_shots.
  Reste à activer une par une : récolte, murs, bâtiments, dons, Jeux de clan, raids, BH, comptes,
  capacités des héros ; Ranked (écran de fin non vu) ; plusieurs combats d'affilée (armée prête ?).
- **Murs** (sans payer) : « Wall x 300 » 1 500 000 (élixir) trouvé page 8 avec 2 crans/page →
  `WALL_SCROLL_NOTCHES` = 5 (1 cran ≈ 107 px), trouvé en 41 s. Ligne « Wall x 25 — New — FREE » :
  lettres lues comme chiffres (6321) → `find_wall` exige une icône de ressource. Sélection : titre
  « Wall (Level 14) » / « … x 1 » → `WALL_SELECTED_TITLE_BOX` (470,740,1400,805) (l'ancien coupait
  le W). `wall_more` 0,75 (l'icône montre le mur au niveau du joueur) → `TEMPLATE_CROPS` (texte seul,
  y≥60) : 0,88. Mode Upgrade More : Remove / +10 Add Wall / +1 Add Wall → `add_one_button` = « Add
  Wall » le plus à droite (jamais le +10). Boutons Upgrade : en mode multiple deux marteaux, `up` ne
  matche plus → repérés par l'icône du prix (`UPGRADE_PRICE_BAND` (250,815,1400,847), pièce/goutte +
  chiffres blancs à gauche, `UPGRADE_ICON_TO_BUTTON` (-48,48)) : or 701/élixir 855 (un mur),
  777/931 (multiple). `BuildPanel.close` : la croix `PANEL_CLOSE_X` (1888,35) d'abord — le clic
  `CLOSE_VILLAGE_CLICK` avait sélectionné un mur niveau 1. Échap ne désélectionne rien sur GPG.
- **Mur payé** (accord de l'utilisateur, `upgrade_walls`, budget or 1,5 M, wall_cost 1500000) :
  1 mur niveau 14 amélioré à l'or, or 10 601 022 → 9 101 022 (−1 500 000 exact), budget décompté,
  arrêt « plus assez de loot ». Le clic Upgrade + Confirm est validé. Mode plusieurs murs
  (`wall_fill`) pas encore payé en vrai.
- `read_village_resources` : élixir noir lu 4 113 785 (tache claire du décor derrière la barre
  translucide) → `prepare_digits` ne garde que les composantes de hauteur ≥ 70 % de la plus haute et
  w ≤ 1,2 h : 113 785. Lectures précédentes (village, scout, fin, bonus, loot restant) inchangées.
- **Récolte** seule : bulle noire 0,99 récoltée ; or/élixir déjà vides (correctement non cliqués).
- **3 combats d'affilée + récolte** (forcée après le 2e) : sans erreur, armée prête à chaque fois
  (« Army Boosted »), côtés bottom_left / top_left / top_right, 2⭐ 3⭐ 3⭐, récolte or 0,95 /
  élixir 0,97 / noir 0,98 entre les combats 2 et 3. Les côtés top_right et top_left posent bien.
- Familier assigné au Champion (Pet House finie) : icône claire en haut à gauche de la carte lue
  comme « x1 » → carte prise pour une troupe. `read_card_count` ne regarde plus que la partie droite
  (left+46) : hero4 reconnu avec et sans familier.
- **Capacités des héros** (4 héros, délai « 4+1 ») : combat 1 → Champion, Reine, Gardien grisés
  (capacité OK) mais Prince des sbires **jamais posé** (un seul clic de pose, non vérifié ; point
  tombé en zone interdite, côté bottom_right). → `unit_on_field` : barre de vie au-dessus de la carte
  `UNIT_HEALTH_BAR_Y` (893,910), H 38-62 S>215 V>160 (l'herbe derrière la barre : S≈139 V≈110,
  faux positifs avec `green_ratio`) ; `deploy_single` : héros/siège vérifié, 3 essais sur d'autres
  points. Combat 2 : siège + 4 héros posés, 4 capacités déclenchées (cartes grises), 3⭐. La reprise
  (2e essai) n'a pas encore été vue en vrai.
- **Première session de l'utilisateur** (profil « Mon compte », 19:01-19:25) : ~12 combats OK, aucune
  déconnexion pendant le farm (les PostMessage comptent comme activité). Constats :
  - murs : 22+ murs d'un coup à 19:06 — le budget = réserves au START (13,99 M / 19 M, comme
    CoCoBot) + loot farmé, pas seulement le loot. Comportement voulu mais à expliquer dans l'UI.
  - « Carte 717/843/1206 pas posée (3/3) » au 1er combat alors que les héros étaient posés ? (à
    revoir : barre de vie pas encore affichée 0,5 s après le clic, ou siège/héros vraiment refusés).
  - 19:25 : fenêtre « Wall Level 14 » à **prix réduit** (bouton vert « Upgrade 1 500 000 / 3 000 000
    barré » au lieu de « Confirm ») → « confirmation impossible », fenêtre laissée ouverte → STOP
    « bouton Battle pas visible » → jeu inactif → déconnexion. Corrigé : `discounted_upgrade_button`
    (gros bouton vert dans `UPGRADE_WINDOW_GREEN_BOX`, jamais le bleu « Wall Ring ») et fermeture
    par la croix (`close_x` ≥ 0,7 : 0,77 sur image agrandie) si rien n'est trouvé.
- Inactivité : rien n'était envoyé pendant les pauses (10-25 min) → popup (« Anyone there? » vers
  5 min 30 sans action). `breaks.keep_alive` toutes les 100-170 s pendant `rest()` (pas en jeu
  fermé) et pendant un long `battle_delay`. Testé : la **molette ne compte pas** (popup à 5 min 30
  malgré 2 crans) ; un **clic** compte → clic sur la barre d'or `KEEP_ALIVE_TAP` (1580,38,1700,58),
  qui n'affiche qu'une info-bulle « Max / Production per hour » : 9 min sans popup.
- `deploy_single` : attend la barre de vie jusqu'à 2,5 s puis 1 seul nouvel essai (recliquer un héros
  déjà posé déclenche sa capacité ; à la 1re session, 0,5 s ne suffisait pas → 3 essais inutiles).
- Non testé : `RANKED_LOOT_*` (écran de fin Ranked), points des autres côtés (`top_right`,
  `bottom_*`), cartes vides grises (`card_alive`) en cours de pose.
- 22:50-22:58 « Murs : confirmation impossible » ×3 : l'app tournait encore avec le code de 19:01
  (pas relancée). Nouveau code vérifié en direct à 23:08 : « prix réduit → bouton Upgrade vert »,
  murs payés or + élixir, puis combat suivant. `python -m cocoto --start TH` (ou
  `Lancer Cocoto + START.bat`) ouvre l'interface et lance le bot sans clic ni popup.
- 2026-11-12, réserves pleines : « Aucun mur à 1 500 000 » → la liste s'est allongée et la ligne
  « Wall x 268 » n'arrivait qu'à la 18ᵉ page. Cause : un WM_MOUSEWHEEL compte pour UN cran quel que
  soit son delta (5/10/15 crans → ~175 px) → `win32.scroll` envoie un message par cran (1 cran ≈
  175 px), `WALL_SCROLL_NOTCHES` 5 → 3, `find_wall` max 30 pages : trouvé en 46 s. Après un achat
  le panneau rouvre à sa position (sous la ligne) → `upgrade_walls` remonte en haut et recherche.
  « confirmation impossible » : `upgrade_button_for` prenait un décor jaune 32x24 derrière les
  boutons → clic sur « Select Row » (rangée de 3 murs, 4,5 M) → icône ≤ 24 px, ratio 0,7-1,4.
  Échec de confirmation → capture `murs_confirmation` dans error_shots.
- 2026-11-12 15:47 « bouton Upgrade introuvable » à chaque essai : les boutons du mur sélectionné
  passent parfois sur **deux lignes** (Info / Select Row / Upgrade More, puis Upgrade or / élixir /
  Wall Ring), prix à y≈904 au lieu de 830 → `UPGRADE_PRICE_BAND` (250,815,1400,847) →
  (250,815,1400,935). 9 captures (1 et 2 lignes) donnent le bon bouton ; en direct 15:59-16:01 :
  14 murs (7 or, 7 élixir) puis « plus assez de loot farmé ».
