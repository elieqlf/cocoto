# Cocoto

Réimplémentation (code nouveau) des fonctionnalités de **CoCoBot 0.0.27**, un bot Clash of Clans.
Comment l'original fonctionne : [docs/ANALYSE.md](docs/ANALYSE.md).

> ⚠️ Automatiser Clash of Clans est contraire aux conditions d'utilisation de Supercell : ton compte
> peut être banni. Utilise-le à tes risques.

## Installation (Windows conseillé, Python 3.10+)

```bash
python -m venv .venv
```
```bash
.venv\Scripts\pip install -r requirements.txt
```

Récupère les templates d'écran et le modèle OCR depuis **ta** copie de CoCoBot :

```bash
python tools/extract_assets.py C:\chemin\CoCoBot0.0.27.exe
```

(`pip install zstandard` ou l'outil `zstd` est nécessaire pour décompresser.)

## Lancement

```bash
python -m cocoto
```

Options : `--instance 2` (2e émulateur / compte, réglages séparés), `--headless TH` (sans interface,
avec le profil actif).

## Choisir le moteur (Config → OPTIONS → Setup)

| Moteur | Quand | Réglage du jeu |
|---|---|---|
| Écran (souris) | Google Play Games au premier plan | plein écran, écran 16:9, échelle Windows 100 % |
| Fenêtre arrière-plan | Google Play Games, tu utilises ton PC en même temps | fenêtre 16:9, ne pas réduire |
| ADB / MuMu | émulateur Android ou téléphone | **1920x1080 conseillé** (MuMu 1728x1080 DPI 240 accepté) ; MuMu 12 : `127.0.0.1:16384` (+32 par instance) |

Le jeu doit être **en anglais**.

## Fonctionnalités

Village principal : armée auto ou par slots, loot minimum + Next, côtés et points de pose
humanisés, sorts, capacités des héros avec délai aléatoire, fin anticipée (`120s 50% 60d 20f`),
Ranked, Cake, demande de renforts, Treasure Event, Star bonus, bonus de ligue, récolte, murs (prix,
plusieurs d'un coup selon le remplissage), bâtiments cochés, suggestions du jeu, laboratoire,
Jeux de clan, dons (précis et libres), raids de la Capitale, réserves pleines (attente, compte
suivant ou visite BH).

Base des ouvriers : étapes 1 et 2, Battle Machine / Copter, jauge de capacité, vitesse 4x,
charrette d'élixir, récolte, bâtiments et murs payés avec les réserves BH, Laboratoire stellaire.

Autour : pauses Play/Break/Closed, plages horaires, délai entre combats, reconnexion automatique,
multi-comptes Supercell ID, profils + codes de partage `COCO-TH-…`, webhook Discord (stats, alertes
avec capture et mention), notifications Windows, contrôle à distance par ton bot Discord
(`/status /start /stop /screen /settings /set /profile`, `pip install discord.py`), multi-instance +
tableau de bord, journal + zip de support, F1 = START/STOP, thèmes.

## Calibrage

Toutes les zones sont dans `cocoto/layout.py` (repère 1920x1080). Pour en corriger une sans toucher
au code, crée `layout.json` dans le dossier de données (`%APPDATA%\Cocoto`) :

```json
{"NEXT_BUTTON": [1667, 773, 1891, 867]}
```

`python tools/calibrate.py --backend adb find_match end return_home` capture le jeu, cherche ces
templates et dessine les zones sur `calibration.png`.

## Tests

```bash
python -m pytest -q
```
