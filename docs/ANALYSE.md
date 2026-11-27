# Rétro-ingénierie de CoCoBot 0.0.27

Fichier analysé : `CoCoBot0.0.27.exe` — 283 952 128 octets —
SHA-256 `b9f6b4c9ed9f130f752a864d0e6ec8f010a7285a799fde1287863d182eb0ebb4`.

Analyse **statique uniquement** (le programme n'a jamais été lancé). Chaque point indique s'il est
*observé* (lu dans le binaire) ou *déduit*.

## 1. Comment le binaire est construit

| Couche | Ce qu'on trouve | Comment on l'a vu |
|---|---|---|
| Lanceur | PE64 Windows GUI, 157 Ko de code, `.rdata` de 283 Mo | en-têtes PE (REA `inspect_artifact` + script) |
| Charge utile | **Nuitka onefile** : en-tête `KAY` puis un flux **zstd** de 880 Mo | chaînes `NUITKA_ONEFILE_PARENT`, `Error, couldn't decode attached data.` |
| Archive | 1513 fichiers : nom UTF-16, taille uint64, CRC32, données (tous les CRC valides) | décompression + `tools/extract_assets.py` |
| Programme | `CoCoBot0.0.27.exe` interne de 138 Mo : le script Python **compilé en C** par Nuitka | — |
| Runtime | Python 3.13, customtkinter, OpenCV, EasyOCR + PyTorch, numpy, scipy, PIL, pyautogui, keyboard, requests | DLL/pyd et table des modules Nuitka |
| Ressources | `img/` : 158 templates d'écran + 76 cartes de dons, `img/lang/*.json` (8 langues), modèles EasyOCR | archive |

Le code de l'application est **un seul module `__main__` d'environ 16 300 lignes**. Nuitka ne garde pas
le bytecode mais garde un « blob » de constantes par module : en le décodant on obtient, dans l'ordre
du source, les **981 fonctions/classes** (nom, paramètres, numéro de ligne), les chaînes (messages,
**docstrings en français**), les nombres (coordonnées, seuils) et les noms d'attributs utilisés.
C'est ce qui a permis de reconstruire la logique sans le code source.

Au lancement, le lanceur décompresse tout dans `%LOCALAPPDATA%\CoCoBot\<version>` (~1,2 Go ; le
programme supprime lui-même les anciennes versions) et affiche un splash Nuitka.

## 2. Architecture du programme (observé)

```
démarrage ─ journal de démarrage, splash, vérif. RAM/AVX, migration des fichiers vers %APPDATA%\CoCoBot
          ─ fenêtre de licence (clé + HWID → serveur) ─ mise à jour automatique
          ─ fenêtre principale customtkinter (TH / BH, onglets Config, Heroes, Upgrade, Stats, Profil)
threads   ─ bot (TH ou BH) ─ AFK checker (popups de déconnexion) ─ ping serveur (2 min)
          ─ tableau de bord multi-instances ─ contrôle à distance (Discord via serveur) ─ chien de garde
```

### Voir et cliquer : 3 moteurs
* **Mode normal** : capture de l'écran (`ImageGrab`) + `pyautogui` ; jeu Google Play Games en plein
  écran **1920x1080** obligatoire (toutes les coordonnées sont dans ce repère).
* **Background mode** : la fenêtre `Clash of Clans` (classe `CROSVM_1`) est capturée avec GDI
  (`PrintWindow`/`GetDIBits`) et reçoit des `PostMessage` (WM_MOUSEMOVE 512, LBUTTONDOWN 513, UP 514,
  MOUSEWHEEL 522, touches) ; l'image est ramenée en 1920x1080 (tout écran 16:9). Garde-fous : jeu
  lancé en administrateur, mise à l'échelle Windows ≠ 100 %, `WM_ACTIVATE` pour « réveiller » le jeu.
* **MuMu mode** : MuMu Player 12 par **ADB** (`exec-out screencap`, `input motionevent`, `input swipe`,
  pincements écrits avec `sendevent` dans `/data/local/tmp/cocobot`, `monkey`/`am force-stop`) ;
  format **1728x1080 DPI 240** imposé, image recomposée en 1920x1080 (coins collés aux bords),
  ports `127.0.0.1:16384 + 32 × (instance-1)`.

### Reconnaître l'écran
* Templates OpenCV `TM_CCOEFF_NORMED` (seuil 0,8 en général, valeurs par bouton), multi-échelles,
  « vu 2 fois au même endroit » pour les panneaux qui glissent.
* Couleurs HSV : bouton Battle jaune, barres de réserves, étoiles argentées, cartes grises (vides),
  bandeau violet (sort), prix rouge (pas assez de ressources), bouton Confirm vert…
* OCR **EasyOCR** sur des chiffres isolés (composantes connexes, image noir sur blanc ×2), avec
  contrôles croisés (nombre de chiffres = nombre de composantes, largeur d'un « 1 » fin…).

## 3. Les fonctionnalités, une par une

### Village principal (boucle `bot_sequence`)
1. **Au START** : village visible (bouton Battle), jeu **en anglais**, bon village (sinon popup), le
   budget des murs/bâtiments = réserves actuelles, **raids de la Capitale** si c'est le Raid Weekend.
2. **Pauses** (Play 40-70 min / Break 10-25 min, option *Closed* = jeu fermé), **plages horaires**,
   **délai entre deux combats**.
3. **Stop when full** : réserves surveillées pleines → compte suivant (multi-comptes), ou visite de la
   **base des ouvriers** (« Then BH »), sinon attente + alerte.
4. **Jeux de clan** : maison des Jeux → défi « Multiplayer » sans contrainte d'armée (liste de mots
   refusés : *using, spell, hero, pet, siege, war, capital, donat…*) ; sinon lancer + Trash (10 min).
5. **Dons** : pastille rouge du chat → bouton Donate → demande précise (icônes « Requested: ») ou
   libre (unités choisies par priorité dans une grille).
6. **Combat** : Battle → (*Ranked* : compteur « 8/18 », limite « Stop at ») → Find a Match → My Army
   (**Cake**, **demande de renforts**) → Attack! → **scout** : OCR du loot disponible, *Next* tant que
   or/élixir/noir < minimum.
7. **Pose** : côté au hasard (jamais deux fois le même), 3-5 crans de dézoom, glissement de 400 px
   (vue en butée), points le long du bord du losange (`MAP_HALF_W=819`, `MAP_HALF_H=614`) ; armée
   **auto** (lecture de la barre : cartes colorées, « x12 », bandeau violet = sort) ou Slot / Count per
   Slot / Spell Slot ; sorts sur une parallèle intérieure ; carte encore pleine → reposée ailleurs.
8. **Héros** : capacité après un délai (« 5 » ou « 2+1 » = 1 à 3 s, tiré à chaque combat).
9. **Pendant le combat** : popup *Pick a Reward!*, **Early end** (`120s 50% 60d 20f` → Surrender),
   1 à 3 gestes de souris « humains ».
10. **Écran de fin** : étoiles (→ Wins/Losses/Stars), loot gagné (contrôlé ≤ loot vu au scout),
    **bonus de ligue** ; Return Home ; **coffre du Treasure Event** ; **Star bonus**.
11. **Après le combat** : **récolte** tous les 7-10 combats, **bâtiments cochés** (payés avec le loot
    farmé, filtre Type, quantité décomptée, ouvrier gardé pour les murs), **suggestions du jeu** (héros
    en option), **laboratoire**, **murs** (prix « Wall cost », *Upgrade More* + « +1 » quand la réserve
    atteint « Walls when storage ≥ X % »), **stats Discord**, **rotation des comptes**.

### Base des ouvriers
Find Now! → « Battle starts in » → héros d'abord (Battle Machine étape 1, Battle Copter étape 2,
échange par le bouton vert) → cartes (auto : « 4x » lu) → vitesse 1x→4x → capacité quand la jauge a
N segments → étape 2 → fin (étoiles : 3 + argentées à l'étape 2, récompenses) → charrette d'élixir,
récolte (3-5 combats), bâtiments puis murs payés avec les réserves BH, **Laboratoire stellaire**.

### Autour du jeu
* **Déconnexions** : thread qui surveille la popup (*inactivity* / *another device*) → alerte → RELOAD
  (re-cliqué si elle revient) → reprise ; coffre éventuel après rechargement.
* **Multi-comptes Supercell ID** : portrait → Settings → flèche bleue → liste SWITCH ID (nom en gras +
  pseudo en dessous, appris et mémorisés) → glissement → chargement → *Welcome Back* → vérification du
  pseudo → profil du compte.
* **Discord** : webhook (embed de stats par mode, alertes avec capture + mention, messages de pause),
  notifications Windows (PowerShell), contrôle à distance `/start /stop /status /screen /settings /set
  /profile` relayé par le serveur de l'auteur.
* **Profils** (`config.json`, `config_bh.json`) : créer/renommer/supprimer/charger, **codes de partage**
  `COCO-TH-…` (JSON → zlib → base64, valeurs privées retirées, contenu nettoyé à l'import).
* **Multi-instance** (`--instance N`, mutex), **tableau de bord** (fichiers d'état partagés), stats de
  session sauvegardées et proposées au relancement, captures d'erreur + **zip de support**, F1 =
  START/STOP, 3 thèmes + thème perso, 10 langues de l'interface.

### Partie commerciale (observée, **non reproduite**)
* Licence : clé + **HWID** (WMI : UUID, carte mère, MachineGuid…) envoyés à
  `https://kalashdu13.pythonanywhere.com/check_license` ; plan renvoyé **signé RSA**
  (`PLAN_PUBLIC_N/E`, vérification PKCS#1 v1.5 SHA-256) ; ping toutes les 2 min (`/ping`).
* *Free* : quota de minutes de murs par jour, badges « PRO ». *Premium* (10 €, à vie) : BH, mode
  arrière-plan, MuMu, Jeux de clan, bâtiments, plages horaires, contrôle à distance, murs illimités.
* Stats en ligne / classement (`/report_attack` signé HMAC, `/my_stats`, `/online_users`), contrôle à
  distance (`/remote_poll`), mise à jour automatique (téléchargement + SHA-256).

## 4. Ce que fait la réimplémentation (`cocoto/`)

Code **nouveau** (aucune ligne copiée), même découpage fonctionnel :

| CoCoBot | Cocoto |
|---|---|
| mode normal / Background / MuMu | `backends/screen.py`, `backends/win32.py`, `backends/adb.py` (tout ADB : MuMu, BlueStacks, LDPlayer, téléphone ; 16:9 conseillé, 16:10 recomposé) |
| templates, couleurs, OCR | `vision.py`, `ocr.py` (EasyOCR, modèle embarqué si extrait) |
| coordonnées | `layout.py` + surcharges `layout.json`, `tools/calibrate.py` |
| boucle TH / BH | `bot_th.py`, `bot_bh.py` |
| combat, scout, Ranked, Cake, renforts | `features/attack.py`, `features/search.py` |
| murs, bâtiments, suggestions, labo | `features/walls.py`, `features/upgrades.py`, `features/panel.py` |
| récolte, coffre, bateau, réserves | `features/village.py` |
| Jeux de clan, dons, raids, comptes | `features/clan_games.py`, `donate.py`, `raids.py`, `accounts.py` |
| pauses, horaires, Closed | `features/breaks.py` |
| déconnexions | `features/reconnect.py` |
| Discord, toasts, support | `notify.py` ; contrôle à distance avec **ton propre bot** : `remote.py` |
| profils, codes, réglages | `storage.py`, `config.py`, `validate.py` |
| multi-instance, tableau de bord | `dashboard.py`, `__main__.py` |
| interface | `ui/` |

Différences voulues : pas de licence ni de serveur (tout est débloqué), pas de stats en ligne ni de
mise à jour automatique, contrôle Discord direct par un bot à toi, l'interface est en FR/EN.

## 5. Limites (à lire)

* Les coordonnées et seuils viennent des constantes du binaire, mais leur **attribution à chaque zone
  est en partie déduite** (Nuitka garde les valeurs, pas toujours leur nom). Elles sont regroupées dans
  `layout.py` et corrigeables sans code ; `tools/calibrate.py` aide à les vérifier sur une capture.
* Rien n'a pu être testé contre le vrai jeu ici (macOS, pas de Clash of Clans) : les tests couvrent la
  logique (parseurs, géométrie, codes, conversion ADB, templates réels, un combat complet simulé).
* Les templates d'image sont ceux de **ta** copie de CoCoBot (extraits par `tools/extract_assets.py`) ;
  ne les redistribue pas (dossier `assets/` ignoré par git).
* Automatiser Clash of Clans est contraire aux conditions d'utilisation de Supercell : risque de
  bannissement du compte.
