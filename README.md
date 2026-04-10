#Baymax — Robot Compagnon Interactif (1 m)

Robot compagnon inspiré de Baymax (Big Hero 6), capable de suivre du regard, détecter les émotions, répondre vocalement et faire des câlins.

## Stack technique

| Couche | Technologies |
|--------|-------------|
| Vision | OpenCV, Mediapipe FaceMesh |
| Audio | Vosk (STT offline), pyttsx3 (TTS) |
| Intelligence | Ollama (tinyllama) / OpenAI API |
| Moteurs | Arduino Nano (6 servos via UART) |
| Écran facial | OLED 1.3" SH1106 (luma.oled) |
| Cerveau | Raspberry Pi 5 (4 Go) |

## Installation

```bash
# Cloner le repo
git clone https://github.com/TON_USER/baymax.git
cd baymax

# Environnement virtuel
python3 -m venv venv
source venv/bin/activate  # Linux/Pi
# ou : venv\Scripts\activate  # Windows

# Dépendances
pip install -r requirements.txt

# Configuration
cp .env.example .env
# Éditer .env si nécessaire
```

## Tests rapides

```bash
# Phase 2 — Vision (sans caméra)
python tests/test_vision.py --dry-run

# Phase 3 — Moteurs (sans Arduino)
python tests/test_motors.py --dry-run
python tests/test_motors.py --simulate

# Avec caméra branchée
python tests/test_vision.py

# Avec Arduino branché
python tests/test_motors.py --port COM3
```

## Structure du projet

```
baymax/
├── main.py                 # Orchestrateur multi-thread
├── config.py               # Constantes et paramètres
├── requirements.txt
├── .env.example
├── modules/
│   ├── vision.py           # Thread caméra + FaceMesh + émotion
│   ├── motors.py           # Thread série Pi → Arduino
│   ├── voice.py            # Thread STT + TTS (Phase 7)
│   ├── brain.py            # LLM / NLU (Phase 8)
│   ├── face_display.py     # OLED expressions (Phase 5)
│   └── safety.py           # Watchdog + mode dégradé
├── arduino/
│   └── baymax_servo.ino    # Firmware Arduino Nano
├── assets/
│   ├── expressions/        # Images BMP 128×64 pour OLED
│   └── vosk-model-fr/      # Modèle Vosk FR (non versionné)
└── tests/
    ├── test_vision.py
    └── test_motors.py
```

## Licence
Projet personnel 