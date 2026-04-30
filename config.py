# config.py - WALL-E configuration centrale
# Modifier les valeurs ici, jamais en dur dans les modules.
# v2.0 : full Ollama. v2.1 : pseudonymisation pour publication portfolio.
#
# IMPORTANT - REPO PUBLIC :
# Les utilisateurs reels (prenoms + dates de naissance) sont charges depuis
# family_local.py qui est gitignore. Si family_local.py n'existe pas, on
# fallback sur family_local.example (template anonymise).
# Pour configurer ton foyer : copier family_local.example.py -> family_local.py
# et editer avec les vrais prenoms et dob.

# === HARDWARE ===
SERIAL_PORT       = "/dev/ttyUSB0"
BAUD_RATE         = 115200
CAMERA_INDEX      = 0
CAMERA_WIDTH      = 640
CAMERA_HEIGHT     = 480
OLED_I2C_ADDRESS  = 0x3C
OLED_WIDTH        = 128
OLED_HEIGHT       = 64

# === VISION (Phase 2) ===
VISION_FPS_TARGET     = 30
VISION_SKIP_FRAMES    = 2
VISION_MIN_CONFIDENCE = 0.5
VISION_MAX_FACES      = 1
EMOTION_SMOOTHING     = 5

# === Seuils de detection d'emotion (Phase 8.4 v2) ===
SMILE_HAPPY_THRESHOLD       = -0.030
MAR_OPEN_MAX                = 0.6
EAR_PAIN_THRESHOLD          = 0.20
BROW_SQUEEZE_PAIN_THRESHOLD = 0.10
SMILE_SAD_THRESHOLD         = -0.060
BROW_DROP_SAD_THRESHOLD     = 0.40
EMOTION_MIN_SCORE           = 0.40
EMOTION_SMOOTHING           = 5
VISION_DEBUG_LOG            = True

# === AUDIO (Phase 7) ===
VOSK_MODEL_PATH   = "assets/vosk-model-fr"
AUDIO_RATE        = 16000
AUDIO_CHUNK       = 4096
TTS_RATE          = 140
TTS_VOLUME        = 0.8

# === MOTEURS (Phase 3) ===
SMOOTHING_ALPHA   = 0.3
IDLE_TIMEOUT      = 5.0
SERVO_RAMP_STEP   = 2

# === BRAIN (Phase 8) - v2.0 OLLAMA OFFLINE ===
LLM_BACKEND                 = "ollama"
OLLAMA_MODEL                = "qwen2.5:3b"
OLLAMA_HOST                 = "http://localhost:11434"

BRAIN_MAX_TOKENS            = 250
BRAIN_MAX_TOOL_ITERATIONS   = 10
BRAIN_MEMORY_TOP_K          = 2
BRAIN_MAX_CALLS_PER_HOUR    = 60
MAX_RESPONSE_LEN            = 80

CHROMA_PATH                 = "data/chroma"

# === UTILISATEURS (chargement dynamique pour repo public) ===
# On tente d'abord family_local (PRIVE, gitignore), sinon fallback sur l'example.
try:
    from family_local import USERS, DEFAULT_USER
except ImportError:
    # Fallback : repo cloned sans family_local.py -> on utilise le template
    from family_local_example import USERS, DEFAULT_USER

# === SECURITE ===
OBSTACLE_MIN_CM   = 15
CPU_TEMP_MAX      = 80
WATCHDOG_TIMEOUT  = 2.0

# === STT (Phase 8.3 partielle, Windows) ===
STT_ENABLED            = True
STT_LANGUAGE           = 'fr-FR'
STT_SAMPLE_RATE        = 16000
STT_DEVICE             = None
STT_SILENCE_THRESHOLD  = 1500
STT_SILENCE_DURATION   = 0.8
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
