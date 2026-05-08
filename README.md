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

## Installation

### Phase A — Dépendances Pi 5

```bash
sudo apt update && sudo apt install -y i2c-tools python3-picamera2
sudo usermod -a -G dialout $USER       # logout/login obligatoire après
pip install -r requirements.txt
```

### Phase B — Configuration OS

```bash
sudo raspi-config       # activer : I2C, SPI, Camera, Serial Hardware (sans console)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b  # ~4.5 GB, **filaire Ethernet recommandé**
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
```

### Phase E — Flash Arduino Mega

1. Sur PC : Arduino IDE → ouvrir `arduino/walle_firmware.ino`
2. Library Manager → installer **MPU6050 (jrowberg)**, **I2Cdevlib**, **NewPing (Tim Eckel)**
3. Sélectionner **Mega 2560** + bon port → Upload
4. Sur le Pi :
```bash
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
| `no module named picamera2` | `sudo apt install python3-picamera2` (apt, pas pip) |
| `i2cdetect ne voit pas 0x70` | recheck câblage TCA (VIN=3.3V, SDA=GPIO2, SCL=GPIO3) |
| Pi reboot pendant inférence | alim 27W officielle obligatoire (sous-tension = throttle) |
| LLM lent > 15s/tour | `vcgencmd get_throttled` doit être 0x0 |
| Pinout TB6612 inversé | corriger `M_PWM[]/M_IN1[]/M_IN2[]` du firmware (cf. Q1) |
| `/dev/ttyACM0` permission refusée | `sudo usermod -a -G dialout $USER` + relog |

## Roadmap

- [x] Phase 17a — capteurs ToF + ultrason via Mega
- [x] Phase 17b — Mecanum 4 moteurs avec safety obstacle
- [ ] Phase 18 — bring-up physique : pinout TB6612 confirmé visuellement
- [ ] Phase 19 — calibration MPU6050 offsets (au repos une fois monté)
- [ ] Phase 20 — tests d'endurance thermique > 30 min
- [ ] Phase 21 — wake word + autonomie batterie 18650
- [ ] Phase 22 — bras servos (DS3218/MG996R), à recommander