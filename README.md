# WALL-E — Robot compagnon offline

Robot compagnon familial inspiré de Pixar, **100 % offline**, basé sur :
- Raspberry Pi 5 16Go (cerveau, vision, conversation Ollama qwen2.5:7b)
- Arduino Mega 2560 (capteurs temps réel + 4 moteurs Mecanum + servos)
- 3 capteurs ToF VL53L1X + ultrason HC-SR04 + IMU MPU6050
- Caméra Module 3 Wide (FOV 102°) avec détection FaceMesh d'émotion
- ChromaDB pour mémoire long terme multi-utilisateur avec ACL parents/enfants

## Architecture

- **`walle.py`** orchestrateur multi-thread : BrainThread, VisionThread, AudioThread, STTThread, KeyboardThread.
- **`brain/`** logique conversationnelle : agent → llm_client (Ollama) → tools (avec ACL par identité) → memory (ChromaDB).
- **`modules/`** hardware : capteurs (Arduino + ToF), moteurs Mecanum, vision, audio, STT.
- **`arduino/walle_firmware.ino`** firmware Mega : protocole série hybride 115200 baud (push capteurs JSON 20Hz + ACK commandes).
- **`brain/world_state.py`** singleton `WORLD` qui agrège ToF + Arduino + Motors et expose les outils physiques au LLM.

## Pré-requis

### Sur le PC de développement (Windows)

- Python 3.14 + venv
- Git Bash + VS Code
- **Arduino IDE 2.3.x** (pour flasher le Mega)
- **Câble USB-A vers USB-B** (câble "imprimante", indispensable pour le Mega)

### Sur le Pi 5

- Raspberry Pi OS **Trixie** (Debian 13) 64-bit, **Python 3.13**
- microSD 16Go minimum (32-64Go recommandé)
- Active Cooler officiel monté avant premier boot (thermal throttle = LLM ralenti)
- Alim USB-C 27W officielle ou équivalent (sous-tension = `vcgencmd get_throttled` non nul)
- Ethernet pour bring-up (Wi-Fi configuré dans Imager en backup)
- SSH activé via Raspberry Pi Imager (Modifier les réglages > Services > SSH avec mot de passe)

## Installation

### Phase A — Dépendances Pi 5

Procédure validée le 09/05/2026 sur Pi OS Trixie + Python 3.13.

```bash
# Update système
sudo apt update && sudo apt full-upgrade -y

# Paquets système (note : libopenblas remplace libatlas sur Trixie+)
sudo apt install -y \
  git python3-pip python3-venv python3-dev \
  build-essential cmake pkg-config swig \
  i2c-tools \
  libopenblas-dev libjpeg-dev libopenjp2-7 libtiff-dev liblgpio-dev \
  rpicam-apps python3-picamera2 \
  portaudio19-dev libsndfile1 alsa-utils \
  curl wget htop

# Groupes Linux (logout/login obligatoire après)
sudo usermod -aG dialout,i2c,gpio,spi,video,audio $USER
exit
ssh kat@walle.local

# Vérification
groups   # doit lister dialout i2c gpio spi video audio

# Clone + venv + libs Python
cd ~ && git clone https://github.com/xeliskatdata-ship-it/WALL-E.git && cd WALL-E
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip

# mediapipe pas dispo Python 3.13 ARM64 -> filtrage temporaire
grep -v "^mediapipe" requirements.txt > /tmp/requirements_pi313.txt
pip install -r /tmp/requirements_pi313.txt

# lgpio non tiré auto par adafruit-blinka 9.x sur Pi 5 + Python 3.13
pip install lgpio
```

### Phase B — Configuration OS

```bash
sudo raspi-config       # activer : I2C, SPI (Camera et Serial Hardware optionnels)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b  # ~4.7 GB, **filaire Ethernet recommandé** (5-15 min)
ollama run qwen2.5:7b "Bonjour, dis-moi en une phrase qui tu es."
# tape /bye pour quitter
```

Vérification après reboot :

```bash
ls /dev/i2c*        # /dev/i2c-1 doit être présent
ls /dev/spidev*     # /dev/spidev0.0 et 0.1 doivent être présents
i2cdetect -y 1      # tableau vide tant que rien n'est branché, normal
```

### Phase C — Vérification config Python

```bash
python -m tests.test_sensors --dry
# Doit afficher [DRY] all green
```

### Phase D — Validation pré-bring-up

```bash
bash scripts/bringup_check.sh
# Tout doit être vert avant Phase E
# Erreurs attendues sur Pi vierge :
#   [WARN] /dev/ttyACM0 absent (Mega pas branché tant que Phase E pas faite)
#   [FAIL] picamera2 manquant (cf. BACKLOG : venv créé sans --system-site-packages)
```

### Phase E — Flash Arduino Mega

1. Sur PC : Arduino IDE → ouvrir `arduino/walle_firmware.ino`
2. Library Manager → installer **MPU6050 by Electronic Cats** (auto-installe `I2Cdev` en dépendance) + **NewPing by Tim Eckel**
3. Sélectionner **Arduino Mega or Mega 2560** + bon port COM → Verify (✓) puis Upload (→)
4. Footprint attendu : ~13800 octets flash (5%), ~880 octets RAM (10%)
5. Débrancher le Mega du PC, le brancher sur un port USB du Pi

```bash
ls /dev/ttyACM*    # /dev/ttyACM0 doit apparaître
python -m tests.test_sensors --live-arduino
# Doit afficher R:PONG + des u=.. ax=.. en boucle 20Hz
```

### Phase F — Bring-up capteurs ToF

```bash
# Câbler 1 seul VL53L1X d'abord (canal 0 du TCA9548A)
i2cdetect -y 1               # doit montrer 0x70
python -m tests.test_sensors --live-tof
# Puis ajouter capteurs sur canaux 1 et 2
```

### Phase G — Lancement complet

```bash
# Test minimal : juste le brain + clavier, pas de vision/audio
python walle.py --user kat --no-vision --no-tts --no-stt

# Test avec capteurs (sans micro/HP encore branchés)
python walle.py --user kat --no-tts --no-stt
# Tape '/sensors' pour voir les 3 ToF + ultrason en direct
# Tape 'tu peux avancer un peu ?' -> brain doit appeler get_distances puis move
```

## Configuration

Les paramètres techniques sont dans `config.py`. Les paramètres famille (USERS, OVERLAYS) sont dans `family_local.py` (gitignore) — voir `family_local_example.py` comme template.

Décisions verrouillées :

| Sujet | Choix |
|---|---|
| LLM | qwen2.5:7b (Ollama 100% offline) |
| Port série Mega | `/dev/ttyACM0` |
| Capteurs ToF | Tool LLM `get_distances()` (lecture seule, accessible à tous sauf unknown) |
| Mouvement | Tool LLM `move(direction, intensity)` (parents + enfants uniquement) |
| Vision | Auto-détection Pi (picamera2) / Windows (cv2) |
| TCA9548A | 0x70, canaux 0/1/2 = G/C/D |
| Duty boot | 60% (débridable runtime via `motors.set_duty_cap`) |
| Watchdog moteurs | 1s |
| Obstacle stop | < 15cm avec moteurs en avant (override Arduino) |

## Commandes en cours d'exécution

| Commande | Effet |
|---|---|
| `[user_id] message` | change le locuteur courant |
| `/who` | qui parle actuellement ? |
| `/users` | liste des users connus |
| `/reset` | efface la conv du locuteur courant |
| `/sensors` | lit les capteurs sans passer par le LLM (debug) |
| `/quit` ou Ctrl+C | sortie propre (motors stop avant fermeture port) |

## Flags CLI

| Flag | Effet |
|---|---|
| `--user XXX` | locuteur par défaut |
| `--no-stt` | désactive le micro |
| `--no-vision` | désactive la caméra (utile si vision pas encore portée picamera2) |
| `--no-tts` | désactive la voix |
| `--no-robot-filter` | TTS sans filtre robot (voix Hortense brute) |
| `--no-hardware` | désactive Arduino + ToF + Motors (test sans hardware) |

## Troubleshooting

| Problème | Solution |
|---|---|
| `ollama: command not found` | `curl -fsSL https://ollama.com/install.sh \| sh` |
| `qwen2.5:7b not found` | `ollama pull qwen2.5:7b` |
| `serial.SerialException` | groupe dialout + port `/dev/ttyACM0` + Mega branché |
| `no module named picamera2` (apt) | `sudo apt install python3-picamera2` |
| `no module named picamera2` (venv) | venv créé sans `--system-site-packages` — recréer venv ou symlink (cf. BACKLOG) |
| `i2cdetect ne voit pas 0x70` | recheck câblage TCA (VIN=3.3V, SDA=GPIO2, SCL=GPIO3) |
| Pi reboot pendant inférence | alim 27W officielle obligatoire (sous-tension = throttle) |
| LLM lent > 15s/tour | `vcgencmd get_throttled` doit être `0x0` |
| Pinout TB6612 inversé | corriger `M_PWM[]/M_IN1[]/M_IN2[]` du firmware (cf. Q1) |
| `/dev/ttyACM0` permission refusée | `sudo usermod -aG dialout $USER` + relog SSH |
| `Package libatlas-base-dev has no installation candidate` | sur Trixie+, utiliser `libopenblas-dev` à la place |
| `mediapipe ERROR: Could not find a version` | pas de wheel Python 3.13 ARM64 — filtrage temporaire (cf. Phase A) |
| `swig: No such file or directory` (sur `pip install lgpio`) | `sudo apt install -y swig` puis re-pip |
| `import board: No module named 'lgpio'` | `pip install lgpio` (dep manquante adafruit-blinka 9.x sur Pi 5) |
| Arduino : `I2Cdev.h: No such file or directory` | Library Manager → installer MPU6050 by Electronic Cats avec ses dépendances |
| Password SSH ne passe pas | password tapé "à l'aveugle" (Linux n'affiche rien), réessayer une fois lentement |

## Roadmap

- [x] Phase 17a — capteurs ToF + ultrason via Mega
- [x] Phase 17b — Mecanum 4 moteurs avec safety obstacle
- [x] Phase 17c — bring-up Pi 5 + flash Mega + comm série validée (session 09/05/26)
- [ ] Phase 18 — câblage capteurs : pinout TB6612 confirmé visuellement + 3 ToF via TCA opérationnels
- [ ] Phase 19 — calibration MPU6050 offsets (au repos une fois monté)
- [ ] Phase 20 — tests d'endurance thermique > 30 min
- [ ] Phase 21 — wake word + autonomie batterie 18650
- [ ] Phase 22 — bras servos (DS3218/MG996R), à recommander

## Documentation complémentaire

- **`BACKLOG.md`** — dettes techniques connues (picamera2 venv, mediapipe Python 3.13, faux positif TCA9548A dans bringup_check)
- **`docs/RECAP_SESSION_*.md`** — historique chronologique des sessions de bring-up et décisions techniques
