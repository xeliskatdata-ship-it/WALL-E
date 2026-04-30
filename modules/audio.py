# modules/audio.py - Phase 8.3 reste : sortie vocale TTS + filtre robot
# v2.5 : backend Piper (offline, multi-plateforme Windows/Pi 5).
#
# Architecture : AudioThread consomme audio_q et synthetise chaque message
# via Piper (modeles ONNX charges en RAM), puis applique un filtre robot
# (pitch shift + bandpass + saturation + crepitement vintage) avant lecture
# par sounddevice.
#
# Voix par defaut : UPMC (jeune adulte masculin francais), avec pitch shift +2
# pour rajeunir. Modele a placer dans models/piper/.

import logging
import threading
from pathlib import Path
from queue import Empty

import numpy as np
import sounddevice as sd
from scipy.signal import butter, sosfilt

from piper import PiperVoice

import config

logger = logging.getLogger("walle.audio")


# === FILTRE ROBOT ===

def _butter_bandpass_sos(lowcut: float, highcut: float, fs: int, order: int = 4):
    """Filtre bandpass Butterworth (effet talkie-walkie)."""
    nyq = 0.5 * fs
    return butter(order, [lowcut / nyq, highcut / nyq], btype="band", output="sos")


def _apply_robot_filter(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Filtre WALL-E vintage : pitch shift + bandpass + saturation douce + crepitement.

    Calibre pour voix UPMC (jeune adulte) -> rajeunissement + cote robot enfantin.
    """
    # 1. Normalisation float32 [-1, 1]
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)
        if np.abs(audio).max() > 1.5:
            audio = audio / 32768.0

    # 2. Pitch shift (rajeunit la voix)
    pitch_steps = getattr(config, "TTS_PITCH_SHIFT", 2)
    if pitch_steps != 0:
        try:
            import librosa
            audio = librosa.effects.pitch_shift(
                y=audio, sr=sample_rate, n_steps=pitch_steps
            )
        except Exception as e:
            logger.warning("Pitch shift echoue (librosa) : %s", e)

    # 3. Bandpass : signature "petit haut-parleur vintage"
    low = getattr(config, "TTS_BANDPASS_LOW", 250)
    high = getattr(config, "TTS_BANDPASS_HIGH", 3000)
    sos = _butter_bandpass_sos(low, high, sample_rate)
    filtered = sosfilt(sos, audio)

    # 4. Saturation douce
    sat = getattr(config, "TTS_SATURATION", 1.4)
    saturated = np.tanh(filtered * sat)

    # 5. Crepitement vintage tres leger (bruit blanc filtre dans la meme bande)
    if getattr(config, "TTS_VINTAGE_NOISE", True):
        noise_lvl = getattr(config, "TTS_NOISE_LEVEL", 0.003)
        noise = np.random.randn(len(saturated)).astype(np.float32) * noise_lvl
        noise_filtered = sosfilt(sos, noise).astype(np.float32)
        saturated = saturated + noise_filtered

    # 6. Recalibrage du niveau
    max_val = np.abs(saturated).max()
    if max_val > 1e-6:
        saturated = saturated / max_val * 0.9

    return saturated.astype(np.float32)


# === SYNTHESE PIPER ===

import re

# Normalisations phonetiques : variantes ecrites -> orthographe que Piper lit correctement.
# On utilise une regex avec mots entiers pour eviter qu'une substitution courte
# ne mange une plus longue (ex: "Walli" matchant l'interieur de "Wallie").
_PHONETIC_PATTERN = re.compile(
    r"\b(WALL-E|Wall-E|wall-e|WALL\.E|Wall\.E|WALLE|Walle|walle|Wally|Walli)\b"
)


def _phonetic_normalize(text: str) -> str:
    """Convertit les variantes ecrites de WALL-E en orthographe phonetique francaise.

    Le texte affiche dans le terminal reste inchange - cette fonction ne touche
    QUE le texte envoye au TTS Piper.
    """
    return _PHONETIC_PATTERN.sub("Wallie", text)


def _synthesize(voice: PiperVoice, text: str):
    """Synthese Piper - retourne (sample_rate, audio_int16_array)."""
    text = _phonetic_normalize(text)
    chunks = []
    for chunk in voice.synthesize(text):
        chunks.append(chunk.audio_int16_array)
    audio = np.concatenate(chunks)
    sample_rate = voice.config.sample_rate
    return sample_rate, audio


# === THREAD ===

class AudioThread(threading.Thread):
    """Thread audio : consomme audio_q et joue chaque message en voix robot.

    Backend Piper - voix chargee une fois au demarrage du thread (~75 Mo RAM
    pour UPMC). Compatible Windows et Pi 5.

    Usage :
        audio_q = Queue()
        at = AudioThread(audio_q, stop_event)
        at.start()
        audio_q.put("Salut, je suis WALL-E")
    """

    def __init__(self, audio_q, stop_event=None,
                 model_path: str = None,
                 robot_filter: bool = True,
                 speaking_event: threading.Event = None):
        super().__init__(name="AudioThread", daemon=True)
        self.audio_q = audio_q
        self.stop_event = stop_event or threading.Event()
        self.model_path = model_path or getattr(
            config, "TTS_PIPER_MODEL", "models/piper/fr_FR-upmc-medium.onnx"
        )
        self.robot_filter = robot_filter
        # Event partage avec STT : True = WALL-E parle, STT doit ignorer ce qu'il capte
        self.speaking_event = speaking_event or threading.Event()
        self._voice = None

    def _load_voice(self):
        """Charge le modele Piper en RAM (~75 Mo pour UPMC)."""
        path = Path(self.model_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Modele Piper introuvable : {path.absolute()}\n"
                f"Telecharge-le depuis https://huggingface.co/rhasspy/piper-voices"
            )
        logger.info("Chargement Piper : %s", path.name)
        self._voice = PiperVoice.load(str(path))
        logger.info("Voix chargee (sample_rate=%d Hz)", self._voice.config.sample_rate)

    def speak(self, text: str):
        """Synthetise + filtre + joue. Bloquant.
        Active speaking_event pendant la lecture pour que STT puisse muter."""
        if not text or not text.strip():
            return
        try:
            sample_rate, audio = _synthesize(self._voice, text)
            if self.robot_filter:
                audio_processed = _apply_robot_filter(audio, sample_rate)
            else:
                audio_processed = audio.astype(np.float32) / 32768.0

            # ON parle : STT doit ignorer
            self.speaking_event.set()
            try:
                sd.play(audio_processed, sample_rate)
                sd.wait()
            finally:
                # Petit delai apres la fin pour laisser l'echo se dissiper
                import time
                time.sleep(0.3)
                self.speaking_event.clear()
        except Exception as e:
            self.speaking_event.clear()
            logger.exception("Erreur TTS pour '%s' : %s", text[:50], e)

    def run(self):
        logger.info("Demarrage AudioThread (Piper, robot_filter=%s)",
                    self.robot_filter)
        try:
            self._load_voice()
        except Exception as e:
            logger.error("Init Piper echouee : %s", e)
            return

        while not self.stop_event.is_set():
            try:
                text = self.audio_q.get(timeout=0.2)
            except Empty:
                continue

            if text is None:  # signal stop propre
                break
            if not text:
                continue

            self.speak(text)

        logger.info("AudioThread arrete")