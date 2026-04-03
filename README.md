# ENSForm – Constructeur de formulaires en ligne

Application web auto-hébergeable construite avec Python/Flask/SQLite.

## Fonctionnalités

- Création, modification, suppression, duplication de formulaires
- Éditeur visuel de questions (drag & drop)
- 8 types de champs : texte court, texte long, nombre, email, date, liste déroulante, choix unique, choix multiple
- Champs obligatoires, options configurables
- Aperçu du formulaire
- Lien public partageable
- Stockage SQLite (zéro configuration)
- Affichage et export CSV des réponses
- **Module Barathon** : graphe orienté des préférences entre participants
  - Gestion d'une liste de participants
  - Anti-doublon par nom
  - Interdiction de s'auto-sélectionner
  - Autocomplétion pour les longues listes
  - Export `.dot` et PNG (nécessite Graphviz)

## Installation

### 1. Prérequis

- Python 3.10+
- (Optionnel) Graphviz pour l'export PNG : `sudo apt install graphviz`

### 2. Installation des dépendances Python

```bash
cd /chemin/vers/form
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Démarrage

```bash
python app.py
```

L'application est accessible sur : http://localhost:5000

### 4. En production (exemple avec Gunicorn)

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

## Structure du projet

```
form/
├── app.py                  # Application principale
├── barathon/
│   ├── __init__.py
│   └── graph.py            # Génération du graphe orienté
├── templates/
│   ├── base.html
│   ├── admin/
│   │   ├── dashboard.html
│   │   ├── form_new.html
│   │   ├── form_edit.html
│   │   ├── form_builder.html
│   │   ├── responses.html
│   │   └── barathon.html
│   └── public/
│       ├── form.html
│       └── thanks.html
├── static/
│   ├── css/style.css
│   └── js/form_builder.js
├── instance/               # Base SQLite (créée automatiquement)
├── requirements.txt
└── README.md
```

## Variables d'environnement

| Variable | Défaut | Description |
|---|---|---|
| `SECRET_KEY` | `change-me` | Clé secrète Flask (à changer en production) |
| `DATABASE_URL` | `sqlite:///instance/forms.db` | URI de base de données |
| `PORT` | `5000` | Port d'écoute |
