# config.py - WALL-E configuration centrale
# Modifier les valeurs ici, jamais en dur dans les modules.
# v2.0 : full Ollama. v2.1 : pseudonymisation pour publication portfolio.
# v2.4 (Phase 17) : Mecanum 4 moteurs + capteurs ToF + qwen2.5:7b sur Pi 5 16Go
#
# IMPORTANT - REPO PUBLIC :
# Les utilisateurs reels (prenoms + dates de naissance) sont charges depuis
# family_local.py qui est gitignore. Si family_local.py n'existe pas, on
# fallback sur family_local_example.py (template anonymise).
# Pour configurer ton foyer : copier family_local_example.py -> family_local.py
# et editer avec les vrais prenoms et dob.

import os
import platform

# === BASE - chemin absolu (compat service systemd au lieu de relatif au cwd) ===
# v2.4 : avant CHROMA_PATH = "data/chroma" plantait quand walle.py etait lance
# depuis un autre cwd (notamment via systemd). On ancre tout sur __file__.
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# === DETECTION PLATEFORME ===
# v2.4 : utilise par modules/vision.py pour basculer picamera2 (Pi) vs cv2 (Windows)
IS_RASPBERRY_PI = (
    platform.system() == "Linux"
    and os.path.exists("/proc/device-tree/model")
)

# === HARDWARE SERIE ===
# v2.4 : Mega 2560 USB-B = /dev/ttyACM0 (Nano CH340 etait /dev/ttyUSB0)
SERIAL_PORT       = "/dev/ttyACM0"
BAUD_RATE         = 115200
SERIAL_TIMEOUT    = 1.0                   # v2.4 : timeout ack R:OK des commandes Arduino

# === CAMERA ===
# Auto-detection picamera2/cv2 dans modules/vision.py via IS_RASPBERRY_PI
CAMERA_INDEX      = 0
CAMERA_WIDTH      = 640
CAMERA_HEIGHT     = 480
CAMERA_FPS        = 30                    # v2.4 : ajout pour cv2.set + picamera2

# === OLED (Phase 11) ===
OLED_I2C_ADDRESS  = 0x3C
OLED_WIDTH        = 128
OLED_HEIGHT       = 64

# === CAPTEURS ToF (Phase 17 v2.4) ===
TCA_ADDRESS          = 0x70               # GERUI a 0x70 ; 2eme TCA en reserve a 0x71
TOF_CHANNELS         = {                  # canaux mux -> position physique
    "left":   0,
    "center": 1,
    "right":  2,
}
TOF_TIMING_BUDGET_MS = 50                 # 50ms = compromis precision/refresh
TOF_RANGE_MODE       = "long"             # short / medium / long (4m max)

# === VISION (Phase 2) ===
VISION_FPS_TARGET     = 30
VISION_SKIP_FRAMES    = 2
VISION_MIN_CONFIDENCE = 0.5
VISION_MAX_FACES      = 1
# v2.4 : EMOTION_SMOOTHING etait defini ici ET plus bas - bug fix, on le garde une seule fois
# (reste defini dans la section emotion)

# === Seuils detection emotion (Phase 8.4 v2.1, calibres) ===
MAR_OPEN_THRESHOLD          = 0.30
EAR_HAPPY_MAX               = 0.25
BROW_DROP_PAIN_THRESHOLD    = 0.45
SMILE_SAD_THRESHOLD         = -0.050
BROW_DROP_SAD_THRESHOLD     = 0.42
EMOTION_MIN_SCORE           = 0.40
EMOTION_SMOOTHING           = 5
VISION_DEBUG_LOG            = True

# === AUDIO (Phase 7) ===
VOSK_MODEL_PATH   = "assets/vosk-model-fr"
AUDIO_RATE        = 16000
AUDIO_CHUNK       = 4096
TTS_RATE          = 140
TTS_VOLUME        = 0.8

# === MOTEURS (Phase 3 + Mecanum v2.4 Phase 17) ===
SMOOTHING_ALPHA   = 0.3
IDLE_TIMEOUT      = 5.0
SERVO_RAMP_STEP   = 2
# v2.4 : safety Mecanum 4 roues (applique cote firmware Mega)
DUTY_BOOT_MAX     = 60                    # plafond duty 0..100 au boot, debridable runtime
MOTOR_WATCHDOG_MS = 1000                  # 1s sans cmd MOTORS -> stop auto cote Arduino

# === BRAIN (Phase 8) - v2.0 OLLAMA OFFLINE / v2.4 qwen2.5:7b ===
LLM_BACKEND                 = "ollama"
OLLAMA_MODEL                = "qwen2.5:7b"      # v2.4 : 3b -> 7b sur Pi 5 16Go
OLLAMA_HOST                 = "http://localhost:11434"
# v2.4 : tuning Ollama Pi 5 (qwen2.5:7b ~4.5GB en RAM, 4 cores Pi 5)
OLLAMA_TIMEOUT              = 60                # 7b plus lent que 3b, marge confortable
OLLAMA_NUM_CTX              = 4096              # contexte large pour tool use + memoire
OLLAMA_NUM_THREAD           = 4                 # 4 cores Pi 5

BRAIN_MAX_TOKENS            = 500               # v2.4 : 250 -> 500 (etait court avec tool use 7b)
BRAIN_MAX_TOOL_ITERATIONS   = 10
BRAIN_MEMORY_TOP_K          = 2
BRAIN_MAX_CALLS_PER_HOUR    = 60
MAX_RESPONSE_LEN            = 80

# v2.4 : path absolu pour compat service systemd (avant : "data/chroma" relatif au cwd)
CHROMA_PATH = os.path.join(_BASE_DIR, "data", "chroma")

# === UTILISATEURS (chargement dynamique pour repo public) ===
# On tente d'abord family_local (PRIVE, gitignore), sinon fallback sur l'example.
try:
    from family_local import USERS, DEFAULT_USER
except ImportError:
    # Fallback : repo cloned sans family_local.py -> on utilise le template
    from family_local_example import USERS, DEFAULT_USER

# === SECURITE ===
OBSTACLE_MIN_CM   = 15                    # cale sur le firmware Arduino (override stop)
CPU_TEMP_MAX      = 80
WATCHDOG_TIMEOUT  = 2.0

# === STT (Phase 8.3 partielle, Windows) ===
STT_ENABLED            = True
STT_LANGUAGE           = 'fr-FR'
STT_SAMPLE_RATE        = 16000
STT_DEVICE             = None
STT_SILENCE_THRESHOLD  = 700   # ancien : 1500
STT_SILENCE_DURATION   = 0.7
STT_MAX_PHRASE         = 10

# === AUTONOMIE (Phase 8.7 v2.0) ===
WAKE_WORD                    = "coucou wall-e"
INITIATIVE_PROACTIVE_ENABLED = True
INITIATIVE_QUIET_HOURS       = (23, 7)
INITIATIVE_MAX_PER_HOUR      = 10
INITIATIVE_MIN_GAP_MINUTES   = (15, 30)

# === INVITES (Phase 8.8 v2.0) ===
GUEST_AUTOPURGE_DAYS         = 7
GUEST_PARENT_APPROVAL_NEEDED = False
GUEST_SIMILARITY_THRESHOLD   = 0.75

# === TTS / Audio (Phase 8.3 v2.5 - backend Piper, compatible Pi 5) ===
TTS_ENABLED         = True
TTS_PIPER_MODEL     = "models/piper/fr_FR-upmc-medium.onnx"
TTS_ROBOT_FILTER    = True
TTS_PITCH_SHIFT     = 4
TTS_BANDPASS_LOW    = 300
TTS_BANDPASS_HIGH   = 3500
TTS_SATURATION      = 1.5
TTS_VINTAGE_NOISE   = True
TTS_NOISE_LEVEL     = 0.001