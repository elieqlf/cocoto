# Cocoto

Bot de farm pour Clash of Clans (Windows + Google Play Games).

> ⚠️ Automatiser Clash of Clans est contraire aux conditions de Supercell : ton compte peut être
> banni. Teste de préférence sur un compte secondaire.

## 1. Installer (une seule fois)

Il faut **Python 3.10+** ([python.org](https://www.python.org/downloads/), coche « Add to PATH »).
Dans le dossier du projet, ouvre un terminal et lance :

```bash
python -m venv .venv
```
```bash
.venv\Scripts\pip install -r requirements.txt
```

(≈ 1 Go à télécharger à cause d'EasyOCR.)

Les images du jeu ne sont **pas** dans le dépôt : elles viennent de **ta propre copie** de
CoCoBot 0.0.27. Lance

```bash
.venv\Scripts\python tools\extract_assets.py C:\chemin\vers\CoCoBot0.0.27.exe
```

Un dossier `assets\` doit apparaître.

## 2. Préparer le jeu

- Clash of Clans **en anglais** (Settings → Language).
- Google Play Games en **fenêtre 16:9** (ou plein écran), échelle Windows **100 %**.
- Ne réduis pas la fenêtre du jeu (tu peux mettre d'autres fenêtres par-dessus).

## 3. Lancer

Double-clic sur **`Lancer Cocoto.bat`**, puis :

1. Config → OPTIONS → Setup → moteur **Fenêtre arrière-plan**.
2. Pour un premier essai : murs et améliorations désactivés.
3. Bouton **START** (ou touche F1). F1 à nouveau pour arrêter.

## En cas de souci

Envoie-moi le journal `%APPDATA%\Cocoto\bot_log.txt` et les captures du dossier
`%APPDATA%\Cocoto\error_shots\` (colle `%APPDATA%\Cocoto` dans la barre d'adresse de l'explorateur).

Documentation complète : [docs/GUIDE.md](docs/GUIDE.md).
