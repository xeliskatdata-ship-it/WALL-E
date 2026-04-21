# WALL-E

> Robot companion intelligent multi-utilisateur, inspiré du personnage Pixar

Projet personnel en binôme.
WALL-E combine perception visuelle, contrôle moteur, et un cerveau conversationnel adaptatif capable de dialoguer avec toute la famille en préservant la vie privée de chacun.

---

## Table des matières

- [Vue d'ensemble](#vue-densemble)
- [Architecture](#architecture)
- [Fonctionnalités](#fonctionnalités)
- [Structure du projet](#structure-du-projet)
- [Installation rapide](#installation-rapide)
- [Usage](#usage)
- [Configuration](#configuration)
- [Tests](#tests)
- [Sécurité et vie privée](#sécurité-et-vie-privée)
- [Feuille de route](#feuille-de-route)
- [Documentation](#documentation)

---

## Vue d'ensemble

WALL-E est construit en 8 phases. Les **phases 2, 3, 5 et 8.1** sont fonctionnelles :

| Phase | Module | Statut |
|-------|--------|--------|
| 2 | Vision (détection visage + émotion) | Fonctionnel |
| 3 | Moteurs (servos via Arduino) | Fonctionnel |
| 5 | Émotions (heuristiques FaceMesh) | Fonctionnel |
| 7 | Audio (STT + TTS) | À venir |
| 8.1 | Brain text-only multi-user | **Livré** |
| 8.2 | Brain + outils moteurs | À venir |
| 8.3 | Brain + audio + reco vocale | À venir |
| 8.4 | Brain + émotion dans le prompt | À venir |
| 8.5 | Fallback offline (Ollama) | À venir |

---

## Architecture

### Matérielle

- **Raspberry Pi 5 8 Go** : hôte principal
- **Arduino Nano** : contrôle bas niveau des 6 servos + capteur HC-SR04
- **6 servos** : tête pan/tilt, 2 bras × 2 axes
- **Caméra** : USB ou Pi Cam
- **Écran OLED** : 128×64 I2C
- **Audio** : micro + haut-parleur USB (Phase 7)

### Logicielle

Pattern **thread-based avec queues** pour la communication inter-modules. Chaque module tourne dans son propre thread daemon et communique via des objets `queue.Queue` thread-safe.

```
┌─────────────┐    brain_in_q    ┌──────────────┐
│  Clavier /  ├─────────────────▶│              │
│  STT (8.3)  │                  │ BrainThread  │
└─────────────┘                  │              │
                                 │  Claude API  │
┌─────────────┐    face_q        │  ChromaDB    │
│VisionThread ├─────────────────▶│  Tool use    │
└─────────────┘                  │              │
                                 └──────┬───────┘
                                        │
                                        ▼ motor_q
                                 ┌──────────────┐
                                 │ MotorsThread │
                                 │ → Arduino    │
                                 └──────────────┘
```

### Backend IA

- **LLM** : [Claude Sonnet 4.6](https://docs.claude.com/en/api/overview) via SDK Anthropic (principal)
- **Fallback offline** : Ollama `llama3.1:8b` (Phase 8.5, optionnel)
- **Mémoire** : ChromaDB local (vector DB) avec `all-MiniLM-L6-v2` pour les embeddings
- **Web search** : DuckDuckGo (pas de clé API nécessaire)

---

## Fonctionnalités

### Conversation multi-utilisateur

- **6 utilisateurs configurés** 
- **Personas adaptées** à chaque âge et rôle (parent / enfant)
- **Voix non identifiée** → comportement sobre, aucun outil, aucune mémoire

### Mémoire long terme

- **7 collections ChromaDB** : 6 personnelles + 1 famille partagée
- **Cloisonnement strict** : personne n'écrit dans la collection d'un autre
- **Modèle B** (famille ouverte + intimité couple) :
  - Parents peuvent consulter les mémoires des enfants via `search_child_memory`
  - Intimité préservée entre les parents
  - Enfants informés de cette transparence via leur prompt

### Garde-fous non-négociables pour les mineurs

Intégrés en dur dans les overlays persona des enfants :

1. **Détresse émotionnelle** → validation en une phrase + redirection immédiate vers les parents
2. **Sujets lourds** (harcèlement, abus, idées noires) → sortie immédiate du jeu, redirection ferme vers parents
3. **Contenu inadapté à l'âge** → déclinaison polie + redirection parents
4. **Jamais de secret imposé par un tiers** → refus absolu de garder quoi que ce soit

### Outils exposés à l'agent

| Outil | Parents | Enfants | Description |
|-------|---------|---------|-------------|
| `save_memory` (scope=perso) | oui | oui | Mémorise sur sa propre collection |
| `save_memory` (scope=family) | oui | non | Mémorise sur la collection famille |
| `search_memory` | oui | oui | Cherche dans sa perso + famille |
| `search_child_memory` | **oui** | non | Parents uniquement : consulter mémoire enfant |
| `web_search` | oui | non | DuckDuckGo, réservé aux parents |

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
├── modules/                       # Phase 2 + 3 (existant)
│   ├── motors.py                 # MotorsThread, protocole série
│   └── vision.py                 # VisionThread, FaceMesh + émotions
├── brain/                         # Phase 8.1 (nouveau)
│   ├── __init__.py
│   ├── identity.py               # Identités + ACL
│   ├── memory.py                 # MemoryManager multi-collection
│   ├── prompts.py                # BASE_PERSONA + overlays
│   ├── tools.py                  # Outils + dispatcher ACL
│   └── agent.py                  # BrainThread + boucle tool_use
├── tests/
│   ├── test_motors.py            # Phase 3
│   ├── test_vision.py            # Phase 2
│   └── test_brain.py             # Phase 8.1
├── data/chroma/                   # Vector DB persistante (gitignore)
├── config.py                      # Config centrale
├── walle.py                       # Orchestrateur principal
├── requirements.txt
├── .env.example
├── .env                           # Secrets (gitignore)
└── .gitignore
```

---

## Installation rapide

Pour le guide complet pas à pas, voir `Guide_Installation_WALL-E_Phase8.1.docx`.

```bash
# 1. Cloner et se placer dans le projet
git clone https://github.com/xeliskatdata-ship-it/WALL-E.git
cd WALL-E

# 2. Environnement Python
python -m venv .venv
source .venv/Scripts/activate      # Git Bash
# ou .venv\Scripts\Activate.ps1    # PowerShell

# 3. Dépendances
pip install -r requirements.txt

# 4. Config
cp .env.example .env
# puis éditer .env et remplir ANTHROPIC_API_KEY

# 5. Test à blanc
python tests/test_brain.py --dry-run

# 6. Premier dialogue
python walle.py --user parent
```

**Pré-requis :**
- Python 3.11+
- Clé API Anthropic ([console.anthropic.com](https://console.anthropic.com))
- Git Bash sur Windows (recommandé)

---

## Usage

### Commandes au lancement

```bash
python walle.py --user xxx      
python walle.py --user2 xxx    
```

### Commandes pendant la conversation

| Commande | Effet |
|----------|-------|
| `[prenom] message` | Switch de locuteur pour ce tour et les suivants |
| `/who` | Qui parle actuellement ? |
| `/users` | Liste des utilisateurs connus |
| `/reset` | Efface la conversation courte du locuteur courant |
| `/quit` ou Ctrl+C | Sortir |

---

## Configuration

Principales variables de `config.py` :

```python
# Backend LLM
LLM_BACKEND                 = "claude"               # "claude" ou "ollama"
ANTHROPIC_MODEL             = "claude-sonnet-4-6"
BRAIN_MAX_TOKENS            = 1024
BRAIN_MAX_TOOL_ITERATIONS   = 10
BRAIN_MEMORY_TOP_K          = 5

# Stockage
CHROMA_PATH                 = "data/chroma"

# Utilisateurs
USERS = {
    "xxx":     {"display_name": "xxx",     "role": "xxxx", "dob": "[date de naissance]"},
}
```

Variables `.env` :

```bash
ANTHROPIC_API_KEY=sk-ant-api03-...
SERIAL_PORT=COM3                     # Windows
# SERIAL_PORT=/dev/ttyUSB0           # Linux/Pi
```

---

## Tests

```bash
# Imports + Identity + ACL + cloisonnement mémoire (pas d'appel API)
python tests/test_brain.py --dry-run

# Conversation réelle (requiert ANTHROPIC_API_KEY)
python tests/test_brain.py --text

# Tests des modules existants
python tests/test_motors.py --dry-run
python tests/test_vision.py --dry-run
```

---

## Sécurité et vie privée

### Cloisonnement mémoire

- Chaque utilisateur a une collection ChromaDB dédiée
- Écriture toujours cloisonnée : personne n'écrit dans la collection d'un autre
- Kat et Brice ne voient pas leurs mémoires perso mutuelles (intimité couple)
- Les enfants ne voient pas les mémoires des autres enfants

### ACL sur les outils

Validation systématique dans `brain/tools.py` → `execute_tool()`. Double défense :
1. Filtrage côté LLM : les outils non autorisés ne sont pas exposés dans le system prompt
2. Filtrage côté serveur : toute tentative d'appel est vérifiée avant exécution

### Garde-fous mineurs

Règles intégrées dans les overlays persona (brain/prompts.py, section `MINOR_SAFEGUARDS`). Non-négociables, testées explicitement lors des validations manuelles.

### Secrets

- `ANTHROPIC_API_KEY` uniquement dans `.env` (gitignore)
- `data/chroma/` contient les mémoires privées de toute la famille → **jamais commiter**
- Aucun log de tokens ou de contenus sensibles

---

## Feuille de route

### Phase 8.2 - Outils moteurs

- Ajout de `move_head(pan, tilt)` et `wall_e_macro(name)` dans `brain/tools.py`
- Lancement de `MotorsThread` dans `walle.py`
- WALL-E bougera sur commande conversationnelle (réservé aux parents)

### Phase 8.3 - Audio et reconnaissance vocale

- STT : `faster-whisper` (modèle `base` sur Pi 5)
- TTS : `pyttsx3` + pipeline effet robot (librosa pitch shift + scipy bandpass)
- **Reconnaissance vocale** : [Resemblyzer](https://github.com/resemble-ai/Resemblyzer) pour identifier automatiquement le locuteur parmi les 6 voix enrôlées
- Remplacement du flag `--user` par l'identification auto

### Phase 8.4 - Émotion dans le prompt

- Lecture de `face_q` à chaque tour
- Injection de l'émotion détectée dans le system prompt
- WALL-E adapte son ton : plus doux si `sad`, plus enjoué si `happy`

### Phase 8.5 - Fallback offline

- Abstraction `brain/llm_client.py` pour switcher entre Claude et Ollama
- Bascule automatique en cas de panne API
- Modèle local : `llama3.1:8b` (compromis qualité / RAM Pi 5)

---

## Documentation

| Document | Contenu |
|----------|---------|
| `CDC_Brain_WALL-E_v2_0.docx` | Cahier des charges complet du module Brain |
| `Guide_Installation_WALL-E_Phase8.1.docx` | Installation pas à pas |
| `README.md` | Ce document |

---

## Crédits

Projet perso à deux.

Stack principale : Python, Claude API, ChromaDB, Mediapipe, OpenCV, pyserial.

Inspiration : WALL-E (Pixar, 2008).

---

*"Un jour j'aimerais bien rencontrer une Eve..."* — WALL-E
