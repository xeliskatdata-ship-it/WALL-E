# config.py - WALL-E configuration centrale
# Modifier les valeurs ici, jamais en dur dans les modules.

# === HARDWARE ===
SERIAL_PORT       = "/dev/ttyUSB0"   # Linux (Pi). Windows : "COM3" ou similaire
BAUD_RATE         = 115200
CAMERA_INDEX      = 0                # 0 = webcam par defaut / Pi Cam
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

MAR_HAPPY_THRESHOLD   = 0.55
EAR_PAIN_THRESHOLD    = 0.20
BROW_SAD_THRESHOLD    = 0.018
EMOTION_MIN_SCORE     = 0.40

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

# === BRAIN (Phase 8) ===
# Backend LLM principal : Claude API. Ollama en fallback optionnel (Phase 8.5)
LLM_BACKEND                 = "claude"              # "claude" ou "ollama"
ANTHROPIC_MODEL             = "claude-sonnet-4-6"
OLLAMA_MODEL                = "llama3.1:8b"         # fallback Phase 8.5
OPENAI_MODEL                = "gpt-4o-mini"         # deprecie, garde pour compat historique
OPENAI_API_KEY              = ""                    # deprecie, utilise .env

# Conversation
BRAIN_MAX_TOKENS            = 1024                  # plafond technique, longueur pilotee par le prompt
BRAIN_MAX_TOOL_ITERATIONS   = 10                    # garde-fou anti-boucle outils
BRAIN_MEMORY_TOP_K          = 5                     # RAG : memoires injectees par tour
BRAIN_MAX_CALLS_PER_HOUR    = 60                    # rate limit interne
BRAIN_OFFLINE_FALLBACK      = False                 # True en Phase 8.5 quand Ollama est pret
MAX_RESPONSE_LEN            = 80                    # mots (Phase 7 audio, non utilise en texte)

# Stockage memoire long terme (vector DB)
CHROMA_PATH                 = "data/chroma"         # relatif a la racine projet

# === UTILISATEURS (Phase 8 Brain multi-user) ===
# user_id -> info. Role 'parent' (full access) ou 'child' (outils restreints).
# Les ages sont calcules dynamiquement depuis dob dans brain/identity.py.
# L'ordre n'a pas d'importance fonctionnelle, mais il structure l'affichage /users.
USERS = {
    "kat":     {"display_name": "Kat",      "role": "parent", "dob": "1975-11-22"},
    "brice":   {"display_name": "Brice",    "role": "parent", "dob": "1982-08-13"},
    "louis":   {"display_name": "Louis",    "role": "child",  "dob": "2009-10-14"},
    "william": {"display_name": "William",  "role": "child",  "dob": "2010-12-23"},
    "raphael": {"display_name": "Raphael",  "role": "child",  "dob": "2014-07-03"},
    "ambre":   {"display_name": "Ambre",    "role": "child",  "dob": "2016-01-18"},
}

# === SECURITE ===
OBSTACLE_MIN_CM   = 15
CPU_TEMP_MAX      = 80
WATCHDOG_TIMEOUT  = 2.0

# === STT (Phase 8.3 partielle, Windows - MVP avant Pi 5) ===
STT_ENABLED            = True      # False = retour clavier seul
STT_LANGUAGE           = 'fr-FR'
STT_SAMPLE_RATE        = 16000
STT_DEVICE             = None      # None = device par defaut Windows
STT_SILENCE_THRESHOLD  = None       # amplitude sous laquelle = silence (ajuster si besoin)
STT_SILENCE_DURATION   = 0.8       # duree de silence pour cloturer la phrase (s)
STT_MAX_PHRASE         = 10        # plafond dur d'une phrase utilisateur (s)
