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
| 2 | Vision (détection visage + émotion) | ✅ Fonctionnel |
| 3 | Moteurs servos (6 axes via Arduino) | ✅ Fonctionnel |
| 5 | Émotions (heuristiques FaceMesh) | ✅ Fonctionnel |
| 8.1 | Brain text-only multi-user | ✅ Livré |
| **8.5** | **Migration full Ollama (offline)** | ✅ **Livré v2.0** |
| **8.6** | **Couche safety déterministe** | ✅ **Livré v2.2** |
| **8.4** | **Émotion injectée dans le prompt** | ✅ **Livré v2.3** |
| 8.2 | Outils moteurs (move_head, macros) | À venir |
| 8.3 | Audio (STT + TTS + VAD) | Partiel (STT en place) |
| 8.7 | Autonomie (wake word + initiative) | À venir |
| 8.8 | Accueil invités (Resemblyzer) | À venir |
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
┌─────────────┐    user_in_q     ┌──────────────┐
│  Clavier /  ├─────────────────▶│              │
│  STT / Voice│                  │ BrainThread  │
└─────────────┘                  │              │
                                 │ Ollama local │
┌─────────────┐    face_q        │  ChromaDB    │
│VisionThread ├─────────────────▶│  Tool use    │
│ (émotion)   │                  │  Safety      │
└─────────────┘                  │  Émotion ctx │
                                 └──────┬───────┘
                                        │
                                        ▼ hardware_q (à venir)
                                 ┌──────────────┐
                                 │ MotorsThread │
                                 │MobilityThread│
                                 │ → Arduino    │
                                 └──────────────┘
```

### Backend IA (v2.3 — full offline)

- **LLM** : [Ollama](https://ollama.com) avec `qwen2.5:3b` (Pi 5 ou dev), ou `qwen2.5:7b` pour plus de qualité. 100% local, coût d'usage zéro.
- **Mémoire long terme** : ChromaDB local (vector DB) avec embeddings `all-MiniLM-L6-v2`
- **Vision** : MediaPipe FaceMesh (468 landmarks) + heuristiques calibrées pour détection d'émotions (happy / sad / pain / neutral)
- **Safety** : couche déterministe (`brain/safety.py`) avec pattern matching sur input et output
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

### Émotion injectée dans le prompt (v2.3)

À chaque tour de conversation, `BrainThread` lit la dernière `FaceData` détectée par `VisionThread` et injecte une consigne de ton dans le system prompt :

| Émotion détectée | Effet sur le ton de WALL-E |
|---|---|
| `happy` (sourire) | Ton enjoué, complice, taquin |
| `sad` (tristesse) | Ton plus doux, chaleureux, pas de blagues |
| `pain` (douleur) | Ton concerné, demande gentille |
| `neutral` ou rien | Comportement nominal |

L'émotion est lissée temporellement sur 5 frames pour éviter les sauts. Les seuils de détection sont calibrés sur des données réelles via le script `calibrate_emotion.py`.

### Garde-fous non-négociables pour les mineurs

Doublement protégés :

1. **Côté LLM** : règles intégrées dans les overlays persona des enfants (`brain/prompts.py`, sections `MINOR_TRANSPARENCY` et `MINOR_SAFEGUARDS`)
2. **Côté safety déterministe** (`brain/safety.py`, Phase 8.6) :
   - **Niveau 2** : détection de détresse sur l'INPUT user (idées noires, violence subie, harcèlement, automutilation) → redirection immédiate, sans appel au LLM
   - **Niveau 1** : pattern matching sur la SORTIE LLM pour les mineurs (sexualité explicite, violence graphique, drogues, méthodes d'automutilation) → remplacement par message safe + log d'alerte

Messages de redirection adaptés au rôle :
- Mineur → « parle à tes parents »
- Adulte → numéros nationaux (3114 prévention suicide, 3919 violences)
- Invité → 119 enfance en danger / 3114

77 tests unitaires valident le corpus (24 phrases de détresse, 25 phrases neutres, 16 sorties problématiques, 12 sorties OK).

### Outils exposés à l'agent

| Outil | Parents | Enfants | Invités | Description |
|-------|---------|---------|---------|-------------|
| `save_memory` (scope=perso) | oui | oui | oui (sa coll.) | Mémorise sur sa propre collection |
| `save_memory` (scope=family) | oui | non | non | Mémorise sur la collection famille |
| `search_memory` | oui | oui | oui (sa coll.) | Cherche dans sa perso + famille |
| `search_child_memory` | **oui** | non | non | Parents uniquement |

Note : `web_search` a été retiré en v2.0 (mode 100% offline).

### Persona WALL-E

- **Curieux et taquin** : pose une question de relance ~1 fois sur 3
- **Complice avec tact** : commente avec personnalité (« moi j'aime bien », « ah tiens »)
- **Un peu seul mais content** : accueil chaleureux, jamais de reproche
- **Rêve d'Eve** : évocation rare (1/10 réponses max), mode espoir
- **Tic vocal** : répétition d'un mot-clé passionnant
- **Adaptation émotionnelle** : ton enjoué si tu souris, plus doux si tu sembles triste
- **Longueur adaptative** : 1-2 phrases par défaut, développe sur demande explicite

---

## Structure du projet

```
WALL-E/
├── arduino/
│   └── walle_servo.ino           # Firmware servos + ultrason
├── modules/
│   ├── motors.py                 # MotorsThread, protocole série
│   ├── vision.py                 # VisionThread, FaceMesh + émotions calibrées
│   └── stt.py                    # STT Windows
├── brain/
│   ├── __init__.py
│   ├── llm_client.py             # Wrapper Ollama compat Anthropic SDK
│   ├── identity.py               # Identités + ACL
│   ├── memory.py                 # MemoryManager multi-collection
│   ├── prompts.py                # BASE_PERSONA + EMOTION_TONE + structure overlays
│   ├── personas_local_example.py # Template overlays (à dupliquer)
│   ├── personas_local.py         # PRIVÉ (gitignore) - tes vraies personas
│   ├── tools.py                  # Outils + dispatcher ACL
│   ├── safety.py                 # Couche safety déterministe (Phase 8.6)
│   └── agent.py                  # BrainThread + boucle tool_use + émotion + safety
├── tests/
│   ├── test_brain.py             # Imports, identité, ACL, mémoire
│   ├── test_safety.py            # 77 tests safety
│   └── test_emotion_prompt.py    # 8 tests injection émotion
├── data/
│   ├── chroma/                   # Vector DB (gitignore)
│   └── safety_alerts.log         # Logs alertes safety (gitignore)
├── config.py                      # Config centrale + seuils émotion
├── family_local_example.py        # Template users (à dupliquer)
├── family_local.py                # PRIVÉ (gitignore) - tes vrais users
├── calibrate_emotion.py           # Script de calibration vision
├── walle.py                       # Orchestrateur
├── requirements.txt
├── .env.example
├── .env                           # Secrets (gitignore)
└── .gitignore
```

---

## Installation rapide

### Prérequis

- **Python 3.11** (recommandé). Python 3.12 OK aussi. **Python 3.14 non supporté** car certains paquets audio (pyaudio) n'ont pas encore de wheel précompilé.

### Étapes

```bash
# 1. Cloner et se placer dans le projet
git clone https://github.com/<your-user>/WALL-E.git
cd WALL-E

# 2. Installer Ollama (binaire système, hors venv)
# Windows : télécharger sur https://ollama.com/download
# Linux  : curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b

# 3. Environnement Python 3.11
py -3.11 -m venv .venv311              # Windows (avec le launcher py)
# ou python3.11 -m venv .venv311       # Linux / Pi
source .venv311/Scripts/activate       # Git Bash sur Windows
# ou source .venv311/bin/activate      # Linux / Pi

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

### 4. (Optionnel) Calibrer la détection d'émotion sur ton visage

Les seuils de détection émotionnelle sont calibrés pour un visage type. Si tu veux les ajuster à ton visage spécifique :

```bash
python calibrate_emotion.py
```

Le script demande de mimer 5 émotions pendant 15 secondes face à la caméra et affiche les valeurs médianes. Compare-les aux seuils dans `config.py` et ajuste si nécessaire.

### 5. Lancer WALL-E

```bash
python walle.py                              # default user, vision + STT actifs
python walle.py --user alice                 # user spécifique
python walle.py --user charlie --no-stt      # désactiver le micro
python walle.py --no-vision                  # désactiver la caméra
python walle.py --no-stt --no-vision         # mode texte pur
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

# Couche safety (77 tests)
python tests/test_safety.py

# Injection émotion dans prompt (8 tests, mock FaceData)
python tests/test_emotion_prompt.py

# Calibration vision (test live, 15 secondes face caméra)
python calibrate_emotion.py
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

### Garde-fous mineurs (Phase 8.6)

`brain/safety.py` filtre la sortie LLM en post-traitement et l'input user en pré-traitement. Voir section [Garde-fous non-négociables pour les mineurs](#garde-fous-non-négociables-pour-les-mineurs).

### Vie privée et offline

- **Aucune donnée envoyée à un service externe** : Ollama tourne 100% en local
- **Pas d'audio enregistré** tant que le wake word n'est pas détecté (Phase 8.7)
- ChromaDB local
- Auto-purge des invités après 7 jours sans interaction

### Pseudonymisation pour publication

Le repo public ne contient **aucune information identifiante** : ni prénoms réels, ni dates de naissance, ni détails de vie privée. Les vraies données du foyer sont stockées dans :

- `family_local.py` (gitignore)
- `brain/personas_local.py` (gitignore)
- `data/` (gitignore — contient ChromaDB et logs safety)
- `.env` (gitignore — secrets éventuels)

Quiconque clone ce repo doit créer ses propres versions de ces fichiers depuis les templates `*_example.py`.

---

## Feuille de route

### Phase 8.2 — Outils moteurs (prochaine)

- `move_head(pan, tilt)` et `wall_e_macro(name)` dans `brain/tools.py`
- Lancement de `MotorsThread` dans `walle.py`
- WALL-E bouge sur commande conversationnelle (réservé parents)

### Phase 8.3 — Audio TTS + VAD complet

- TTS : `pyttsx3` + pipeline effet robot (librosa pitch shift + scipy bandpass)
- VAD continu : `webrtcvad`
- WALL-E répond en vraie voix robot vintage

### Phase 8.7 — Autonomie

- Wake word « Coucou WALL-E » via `openWakeWord` (offline, léger)
- `InitiativeThread` : WALL-E peut démarrer une conversation
- Mode proactif : relances aléatoires (10/h max, désactivé 23h-7h)

### Phase 8.8 — Accueil invités

- Voice ID via [Resemblyzer](https://github.com/resemble-ai/Resemblyzer)
- Enrôlement à la volée avec consentement vocal
- Persona child + safeguards complets si invité mineur
- Auto-purge mémoire à J+7 (J+90 si validé par un parent)

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
| `CDC_WALL-E_v2.3.docx` | Cahier des charges complet (v2.3 — Phase 8.4 livrée) |
| `MIGRATION_v2.0.md` | Guide step-by-step migration Anthropic → Ollama |
| `README.md` | Ce document |

---

## Stack technique

Python 3.11, **Ollama** (qwen2.5:3b), ChromaDB, MediaPipe, OpenCV, pyserial, pyaudio, SpeechRecognition, FastAPI (Phase 10), React Native (Phase 10).

Inspiration : WALL-E (Pixar, 2008).

---

*« Un jour j'aimerais bien rencontrer une Eve... »* — WALL-E
