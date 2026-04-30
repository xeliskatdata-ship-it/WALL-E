# WALL-E

> Robot companion intelligent multi-utilisateur, inspiré du personnage Pixar.

Projet personnel.
WALL-E combine perception visuelle, contrôle moteur, et un cerveau conversationnel **100% local et offline** capable de dialoguer avec toute une famille en préservant la vie privée de chacun.

---

## Table des matières

- [Vue d'ensemble](#vue-densemble)
- [Architecture](#architecture)
- [Fonctionnalités](#fonctionnalités)
- [Structure du projet](#structure-du-projet)
- [Installation rapide](#installation-rapide)
- [Configuration du foyer](#configuration-du-foyer)
- [Usage](#usage)
- [Tests](#tests)
- [Sécurité et vie privée](#sécurité-et-vie-privée)
- [Feuille de route](#feuille-de-route)
- [Documentation](#documentation)

---

## Vue d'ensemble

WALL-E est construit en plusieurs phases successives :

| Phase | Module | Statut |
|-------|--------|--------|
| 2 | Vision (détection visage + émotion) | Fonctionnel |
| 3 | Moteurs servos (6 axes via Arduino) | Fonctionnel |
| 5 | Émotions (heuristiques FaceMesh) | Fonctionnel |
| 8.1 | Brain text-only multi-user | Livré |
| **8.5** | **Migration full Ollama (offline)** | **Livré v2.0** |
| 8.6 | Couche safety déterministe | À venir |
| 8.2 | Outils moteurs (move_head, macros) | À venir |
| 8.3 | Audio (STT + TTS + VAD) | Partiel (STT en place) |
| 8.7 | Autonomie (wake word + initiative) | À venir |
| 8.8 | Accueil invités (Resemblyzer) | À venir |
| 8.4 | Émotion injectée dans le prompt | À venir |
| 9 | Mobilité (Mecanum) + corps Pi 5 | À venir |
| 10 | Application mobile (parents) | À venir |

---

## Architecture

### Matérielle

- **Raspberry Pi 5 8 Go** (avec NVMe + refroidissement actif) : hôte du brain + LLM local + vision
- **Arduino Mega2560** + shield 4Motor&9Servo TB6612 : contrôle bas niveau
- **6 servos** : tête pan/tilt + 2 bras × 2 axes
- **4 roues Mecanum** 80mm + moteurs JGB37 12V DC : déplacement omnidirectionnel
- **Caméra** : Raspberry Pi Camera Module 3 Wide
- **Ultrason** : HC-SR04
- **Écran OLED** : 128×64 I2C
- **Audio** : micro + haut-parleur USB

### Logicielle

Pattern **thread-based avec queues** pour la communication inter-modules. Chaque module tourne dans son propre thread daemon et communique via des objets `queue.Queue` thread-safe.

```
┌─────────────┐    brain_in_q    ┌──────────────┐
│  Clavier /  ├─────────────────▶│              │
│  STT / Voice│                  │ BrainThread  │
└─────────────┘                  │              │
                                 │ Ollama local │
┌─────────────┐    face_q        │  ChromaDB    │
│VisionThread ├─────────────────▶│  Tool use    │
└─────────────┘                  │  Safety      │
                                 └──────┬───────┘
                                        │
                                        ▼ hardware_q
                                 ┌──────────────┐
                                 │ MotorsThread │
                                 │MobilityThread│
                                 │ → Arduino    │
                                 └──────────────┘
```

### Backend IA (v2.0 — full offline)

- **LLM** : [Ollama](https://ollama.com) avec `qwen2.5:3b` (Pi 5) ou `qwen2.5:7b` (machine de dev). 100% local, coût d'usage zéro.
- **Mémoire long terme** : ChromaDB local (vector DB) avec embeddings `all-MiniLM-L6-v2`
- **Voice ID** (Phase 8.8) : Resemblyzer pour identifier les utilisateurs + accueillir les invités à la volée
- **Wake word** (Phase 8.7) : openWakeWord, phrase « Coucou WALL-E »

L'abstraction LLM est dans `brain/llm_client.py` avec une interface compatible Anthropic SDK, ce qui permet de revenir à Claude API en changeant un seul import si besoin.

---

## Fonctionnalités

### Conversation multi-utilisateur

- Configuration flexible du foyer (1 à N parents + N enfants) via `family_local.py`
- **Personas adaptées** à chaque âge et rôle (parent / enfant)
- **Voix non identifiée** → comportement sobre, aucun outil, aucune mémoire
- **Invité (Phase 8.8)** : enrôlement à la voix avec consentement, mémoire 7 jours par défaut

### Mémoire long terme

- **N+1 collections ChromaDB** : une par membre du foyer + une famille partagée
- **Cloisonnement strict** : personne n'écrit dans la collection d'un autre
- **Modèle B** (famille ouverte + intimité couple) :
  - Parents peuvent consulter les mémoires des enfants via `search_child_memory`
  - Intimité préservée entre les parents (pas d'accès mutuel aux mémoires perso)
  - Enfants informés de cette transparence via leur prompt système

### Garde-fous non-négociables pour les mineurs

Intégrés en dur dans les overlays persona des enfants, et renforcés en Phase 8.6 par une couche `safety.py` déterministe :

1. **Détresse émotionnelle** → validation en une phrase + redirection vers les parents
2. **Sujets lourds** (harcèlement, abus, idées noires) → sortie immédiate du jeu, redirection ferme
3. **Contenu inadapté à l'âge** → déclinaison polie + redirection parents
4. **Jamais de secret imposé par un tiers** → refus absolu

Ces règles s'appliquent aux enfants connus **et** aux invités mineurs.

### Outils exposés à l'agent

| Outil | Parents | Enfants | Invités | Description |
|-------|---------|---------|---------|-------------|
| `save_memory` (scope=perso) | oui | oui | oui (sa coll.) | Mémorise sur sa propre collection |
| `save_memory` (scope=family) | oui | non | non | Mémorise sur la collection famille |
| `search_memory` | oui | oui | oui (sa coll.) | Cherche dans sa perso + famille |
| `search_child_memory` | **oui** | non | non | Parents uniquement |

Note : `web_search` a été retiré en v2.0 (mode 100% offline).

### Persona WALL-E

- **Curieux** : pose une question de relance 2 fois sur 3
- **Indiscret avec tact** : rebondit sur sa mémoire long terme
- **Un peu seul mais content** : accueil chaleureux, jamais de reproche
- **Rêve d'Eve** : évocation rare (1/10 réponses max), mode espoir
- **Tic vocal** : répétition d'un mot-clé passionnant
- **Longueur adaptative** : 2-3 phrases par défaut, développe sur demande explicite

---

## Structure du projet

```
WALL-E/
├── arduino/
│   └── walle_servo.ino           # Firmware servos + ultrason
├── modules/
│   ├── motors.py                 # MotorsThread, protocole série
│   ├── vision.py                 # VisionThread, FaceMesh + émotions
│   └── stt.py                    # STT Windows
├── brain/
│   ├── __init__.py
│   ├── llm_client.py             # Wrapper Ollama compat Anthropic SDK
│   ├── identity.py               # Identités + ACL
│   ├── memory.py                 # MemoryManager multi-collection
│   ├── prompts.py                # BASE_PERSONA + structure overlays
│   ├── personas_local_example.py # Template overlays (à dupliquer)
│   ├── personas_local.py         # PRIVÉ (gitignore) - tes vraies personas
│   ├── tools.py                  # Outils + dispatcher ACL
│   └── agent.py                  # BrainThread + boucle tool_use
├── tests/
├── data/chroma/                   # Vector DB (gitignore)
├── config.py                      # Config centrale
├── family_local_example.py        # Template users (à dupliquer)
├── family_local.py                # PRIVÉ (gitignore) - tes vrais users
├── walle.py                       # Orchestrateur
├── requirements.txt
├── .env.example
├── .env                           # Secrets (gitignore)
└── .gitignore
```

---

## Installation rapide

```bash
# 1. Cloner et se placer dans le projet
git clone https://github.com/<your-user>/WALL-E.git
cd WALL-E

# 2. Installer Ollama (binaire système, hors venv)
# Windows : télécharger sur https://ollama.com/download
# Linux  : curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b

# 3. Environnement Python
python -m venv .venv
source .venv/Scripts/activate      # Git Bash sur Windows
# ou source .venv/bin/activate     # Linux / Pi

# 4. Dépendances
pip install -r requirements.txt
```

---

## Configuration du foyer

WALL-E est livré avec des templates anonymisés. Pour configurer ton foyer réel :

### 1. Créer ton fichier d'utilisateurs (privé)

```bash
cp family_local_example.py family_local.py
```

Édite `family_local.py` avec les vrais user_id, prénoms, rôles et dates de naissance :

```python
USERS = {
    "alice":    {"display_name": "Alice",   "role": "parent", "dob": "1985-04-12"},
    "bob":      {"display_name": "Bob",     "role": "parent", "dob": "1983-08-30"},
    "charlie":  {"display_name": "Charlie", "role": "child",  "dob": "2012-02-18"},
}

DEFAULT_USER = "alice"
```

### 2. Créer tes overlays persona (privé)

```bash
cp brain/personas_local_example.py brain/personas_local.py
```

Édite `brain/personas_local.py` pour adapter les personas (centres d'intérêt, ton, contexte) à chaque membre du foyer. Les `user_id` doivent matcher ceux de `family_local.py`.

### 3. Vérifier le .gitignore

`family_local.py` et `brain/personas_local.py` sont déjà dans le `.gitignore`. Vérifie bien avant le premier `git push` :

```bash
git check-ignore family_local.py brain/personas_local.py
# Doit lister les deux fichiers (= ignorés, OK)
```

### 4. Lancer WALL-E

```bash
python walle.py                         # default user depuis family_local.py
python walle.py --user alice            # user spécifique
python walle.py --user charlie --no-stt # désactiver le micro
```

---

## Usage

### Commandes pendant la conversation

| Commande | Effet |
|----------|-------|
| `[user_id] message` | Switch de locuteur pour ce tour et les suivants |
| `/who` | Qui parle actuellement ? |
| `/users` | Liste des utilisateurs connus |
| `/reset` | Efface la conversation courte du locuteur courant |
| `/quit` ou Ctrl+C | Sortir |

---

## Tests

```bash
# Imports + Identity + ACL + cloisonnement mémoire (pas d'appel LLM)
python tests/test_brain.py --dry-run

# Conversation réelle (requiert Ollama service actif)
python tests/test_brain.py --text

# Modules
python tests/test_motors.py --dry-run
python tests/test_vision.py --dry-run
python tests/test_mic.py
python tests/test_stt_thread.py
```

---

## Sécurité et vie privée

### Cloisonnement mémoire

- Chaque utilisateur a une collection ChromaDB dédiée
- Écriture toujours cloisonnée : personne n'écrit dans la collection d'un autre
- Les parents ne voient pas leurs mémoires perso mutuelles (intimité couple)
- Les enfants ne voient pas les mémoires des autres enfants
- Les invités ont une collection éphémère (purge automatique J+7)

### ACL sur les outils

Validation systématique dans `brain/tools.py` → `execute_tool()`. Double défense :

1. Filtrage côté LLM : les outils non autorisés ne sont pas exposés dans le system prompt
2. Filtrage côté serveur : toute tentative d'appel est vérifiée avant exécution

### Garde-fous mineurs

Règles intégrées dans les overlays persona (`brain/prompts.py`, sections `MINOR_TRANSPARENCY` et `MINOR_SAFEGUARDS`) et renforcées par `brain/safety.py` (Phase 8.6) qui filtre la sortie LLM en post-traitement.

### Vie privée et offline

- **Aucune donnée envoyée à un service externe** : Ollama tourne 100% en local
- **Pas d'audio enregistré** tant que le wake word n'est pas détecté (Phase 8.7)
- ChromaDB local
- Auto-purge des invités après 7 jours sans interaction

### Pseudonymisation pour publication

Le repo public ne contient **aucune information identifiante** : ni prénoms réels, ni dates de naissance, ni détails de vie privée. Les vraies données du foyer sont stockées dans :

- `family_local.py` (gitignore)
- `brain/personas_local.py` (gitignore)
- `data/` (gitignore — contient ChromaDB)
- `.env` (gitignore — secrets éventuels)

Quiconque clone ce repo doit créer ses propres versions de ces fichiers depuis les templates `*_example.py`.

---

## Feuille de route

### Phase 8.6 — Couche safety déterministe

- Création de `brain/safety.py` avec 3 niveaux de filtrage (pattern matching, détection détresse, contradiction prompt)
- Compense la moindre fiabilité des modèles locaux pour les garde-fous mineurs

### Phase 8.2 — Outils moteurs

- `move_head(pan, tilt)` et `wall_e_macro(name)` dans `brain/tools.py`
- Lancement de `MotorsThread` dans `walle.py`
- WALL-E bouge sur commande conversationnelle (réservé parents)

### Phase 8.3 — Audio TTS + VAD

- TTS : `pyttsx3` + pipeline effet robot (librosa pitch shift + scipy bandpass)
- VAD continu : `webrtcvad`

### Phase 8.7 — Autonomie

- Wake word « Coucou WALL-E » via `openWakeWord` (offline, léger)
- `InitiativeThread` : WALL-E peut démarrer une conversation
- Mode proactif : relances aléatoires (10/h max, désactivé 23h-7h)

### Phase 8.8 — Accueil invités

- Voice ID via [Resemblyzer](https://github.com/resemble-ai/Resemblyzer)
- Enrôlement à la volée avec consentement vocal
- Persona child + safeguards complets si invité mineur
- Auto-purge mémoire à J+7 (J+90 si validé par un parent)

### Phase 8.4 — Émotion dans le prompt

- Lecture de `face_q` à chaque tour
- Injection de l'émotion détectée dans le system prompt

### Phase 9 — Mobilité + corps Pi 5

- Migration complète Windows → Raspberry Pi 5
- `picamera2` pour la caméra
- Firmware étendu Mega2560 + 4 roues Mecanum + driver TB6612
- Outil agentique `move_robot(direction, distance, speed)` (parents only)

### Phase 10 — Application mobile

- API REST + WebSocket sur le Pi 5 (FastAPI)
- App React Native / Expo (iOS + Android), réservée aux parents
- Authentification JWT, accès distant via Tailscale VPN

---

## Documentation

| Document | Contenu |
|----------|---------|
| `CDC_WALL-E_v2.1.docx` | Cahier des charges complet |
| `MIGRATION_v2.0.md` | Guide step-by-step migration Anthropic → Ollama |
| `README.md` | Ce document |

---

## Stack technique

Python, **Ollama** (qwen2.5:3b), ChromaDB, Mediapipe, OpenCV, pyserial, FastAPI (Phase 10), React Native (Phase 10).

Inspiration : WALL-E (Pixar, 2008).

---

*« Un jour j'aimerais bien rencontrer une Eve... »* — WALL-E
