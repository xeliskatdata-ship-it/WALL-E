# modules/stt.py
# STTThread : capture micro -> transcription FR -> out_q ("voice", text)
# Auto-calibration du seuil au boot : mesure bruit ambiant 1s, seuil = max x 2
# Si silence_threshold fourni explicitement, on skip la calibration (override manuel)

import threading
import queue
import time
import numpy as np
import sounddevice as sd
import speech_recognition as sr


class STTThread(threading.Thread):
    def __init__(self, out_q, stop_event,
                 language="fr-FR",
                 sample_rate=16000,
                 device=None,
                 silence_threshold=None,      # None = auto-calibration
                 silence_duration=0.8,
                 max_phrase_duration=10,
                 calibration_duration=1.0,
                 debug=True):
        super().__init__(daemon=True, name="STTThread")
        self.out_q = out_q
        self.stop_event = stop_event
        self.language = language
        self.sample_rate = sample_rate
        self.device = device
        
        self.silence_threshold = silence_threshold  # fixe a None ici, calibre dans run()
        self.silence_duration = silence_duration
        self.max_phrase_duration = max_phrase_duration
        self.calibration_duration = calibration_duration
        self.debug = debug
        
        # Chunks 100ms
        self.chunk_duration = 0.1
        self.chunk_size = int(self.sample_rate * self.chunk_duration)
        
        self.recognizer = sr.Recognizer()

    def _calibrate(self):
        # Mesure du bruit ambiant : amplitude max pendant calibration_duration secondes
        # Seuil final = max(300, bruit_max * 2) pour rester au-dessus du bruit de fond
        samples = int(self.calibration_duration * self.sample_rate)
        print(f"[STT] Calibration bruit ambiant ({self.calibration_duration}s, reste silencieuse)...")
        
        audio = sd.rec(samples, samplerate=self.sample_rate, channels=1,
                       dtype="int16", device=self.device)
        sd.wait()
        
        noise_max = int(np.abs(audio).max())
        noise_mean = float(np.abs(audio).mean())
        threshold = max(300, noise_max * 2)
        
        print(f"[STT] Bruit max={noise_max}, moy={noise_mean:.1f} -> seuil={threshold}")
        return threshold

    def _record_phrase(self):
        buffer = []
        silence_chunks = 0
        max_silence_chunks = int(self.silence_duration / self.chunk_duration)
        max_total_chunks = int(self.max_phrase_duration / self.chunk_duration)
        voice_started = False
        peak_amp = 0  # pour debug
        
        with sd.InputStream(samplerate=self.sample_rate, channels=1,
                            dtype="int16", device=self.device,
                            blocksize=self.chunk_size) as stream:
            for _ in range(max_total_chunks):
                if self.stop_event.is_set():
                    return None, 0
                
                chunk, _ = stream.read(self.chunk_size)
                amplitude = int(np.abs(chunk).max())
                peak_amp = max(peak_amp, amplitude)
                
                if amplitude > self.silence_threshold:
                    buffer.append(chunk)
                    silence_chunks = 0
                    voice_started = True
                elif voice_started:
                    buffer.append(chunk)
                    silence_chunks += 1
                    if silence_chunks >= max_silence_chunks:
                        break
        
        if not buffer or not voice_started:
            return None, peak_amp
        
        return np.concatenate(buffer, axis=0), peak_amp

    def run(self):
        # Auto-calibration si seuil non fourni
        if self.silence_threshold is None:
            try:
                self.silence_threshold = self._calibrate()
            except Exception as e:
                print(f"[STT] Calibration echouee ({e}), fallback seuil=500")
                self.silence_threshold = 500
        
        print(f"[STT] Ecoute active (seuil={self.silence_threshold}, langue={self.language})")
        
        # Boucle de heartbeat : si rien detecte pendant N cycles, on affiche le pic observe
        # pour diagnostiquer un seuil trop haut
        empty_cycles = 0
        
        while not self.stop_event.is_set():
            try:
                audio_np, peak = self._record_phrase()
            except Exception as e:
                print(f"[STT] Erreur capture : {e}")
                time.sleep(0.5)
                continue
            
            if audio_np is None:
                empty_cycles += 1
                if self.debug and empty_cycles % 5 == 0 and peak > 0:
                    # Un bruit a ete capte mais n'a pas franchi le seuil
                    print(f"[STT] (debug) pic={peak} < seuil={self.silence_threshold}, parle plus fort ou baisse le seuil")
                continue
            
            empty_cycles = 0
            audio_data = sr.AudioData(audio_np.tobytes(), self.sample_rate, 2)
            
            try:
                text = self.recognizer.recognize_google(audio_data, language=self.language)
            except sr.UnknownValueError:
                if self.debug:
                    print(f"[STT] (debug) audio capte (pic={peak}) mais pas compris par Google")
                continue
            except sr.RequestError as e:
                print(f"[STT] Erreur API Google : {e}")
                time.sleep(1)
                continue
            
            text = text.strip()
            if not text:
                continue
            
            try:
                self.out_q.put_nowait(("voice", text))
            except queue.Full:
                print("[STT] out_q pleine, message perdu")
        
        print("[STT] Thread arrete proprement")
