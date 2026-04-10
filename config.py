# config.py — Baymax configuration centrale
# Modifier les valeurs ici, jamais en dur dans les modules.

# === HARDWARE ===
SERIAL_PORT       = "/dev/ttyUSB0"   # Linux (Pi). Windows : "COM3" ou similaire
BAUD_RATE         = 115200
CAMERA_INDEX      = 0                # 0 = webcam par défaut / Pi Cam
CAMERA_WIDTH      = 640
CAMERA_HEIGHT     = 480
OLED_I2C_ADDRESS  = 0x3C
OLED_WIDTH        = 128
OLED_HEIGHT       = 64

# === VISION ===
VISION_FPS_TARGET     = 30          # FPS demandé à la caméra
VISION_SKIP_FRAMES    = 2           # Traite 1 frame sur N (économie CPU)
VISION_MIN_CONFIDENCE = 0.5         # Seuil détection visage FaceMesh
VISION_MAX_FACES      = 1           # On ne suit qu'un seul visage
EMOTION_SMOOTHING     = 5           # Moyenne glissante sur N frames

# Seuils heuristiques émotions (Phase 5, préremplis)
MAR_HAPPY_THRESHOLD   = 0.55        # Mouth Aspect Ratio pour joie
EAR_PAIN_THRESHOLD    = 0.20        # Eye Aspect Ratio pour douleur
BROW_SAD_THRESHOLD    = 0.018       # Distance sourcils normalisée pour tristesse
EMOTION_MIN_SCORE     = 0.40        # En dessous = neutre

# === AUDIO (Phase 7) ===
VOSK_MODEL_PATH   = "assets/vosk-model-fr"
AUDIO_RATE        = 16000
AUDIO_CHUNK       = 4096
TTS_RATE          = 140
TTS_VOLUME        = 0.8

# === MOTEURS (Phase 3) ===
SMOOTHING_ALPHA   = 0.3             # Filtre passe-bas angles tête
IDLE_TIMEOUT      = 5.0             # Secondes sans visage avant idle
SERVO_RAMP_STEP   = 2               # Degrés par cycle Arduino

# === BRAIN (Phase 8) ===
LLM_BACKEND       = "ollama"        # "ollama" ou "openai"
OLLAMA_MODEL      = "tinyllama"
OPENAI_MODEL      = "gpt-4o-mini"
OPENAI_API_KEY    = ""
MAX_RESPONSE_LEN  = 80

# === SÉCURITÉ ===
OBSTACLE_MIN_CM   = 15
CPU_TEMP_MAX      = 80
WATCHDOG_TIMEOUT  = 2.0
