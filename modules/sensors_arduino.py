# modules/sensors_arduino.py - bridge serie Mega <-> Pi
# v2.4 : NEW. Centralise l'ouverture du port serie pour eviter le conflit
# motors.py (qui ouvrait son propre port avant) vs sensors.

import json
import threading
import time
from queue import Queue, Empty
from collections import deque

import serial

import config


class ArduinoBridge:
    # Singleton de fait : on instancie une fois dans world_state.WORLD.
    # Lit en arriere-plan les push S:{...} et stocke le dernier etat sous lock.
    # Les commandes (MOTORS/SERVO/STOP/PING) sont envoyees sync avec attente R:OK.

    def __init__(self, port=None, baud=None):
        self.port = port or config.SERIAL_PORT
        self.baud = baud or config.BAUD_RATE
        self._ser = None
        self._lock = threading.Lock()
        self._latest = {}
        self._latest_ts = 0.0
        self._ack_q = Queue(maxsize=8)
        self._stop = threading.Event()
        self._thr = None
        self._history = deque(maxlen=20)   # debug : 20 derniers push

    def open(self):
        # Ouverture + petite tempo : Mega reset au DTR, faut le laisser booter
        self._ser = serial.Serial(self.port, self.baud, timeout=config.SERIAL_TIMEOUT)
        time.sleep(2.0)
        self._ser.reset_input_buffer()
        self._stop.clear()
        self._thr = threading.Thread(target=self._reader_loop, daemon=True)
        self._thr.start()

    def close(self):
        self._stop.set()
        if self._thr:
            self._thr.join(timeout=1.0)
        if self._ser:
            self._ser.close()

    def _reader_loop(self):
        # boucle lecteur : separe les lignes S:{...} (capteurs) des R:... (acks)
        while not self._stop.is_set():
            try:
                line = self._ser.readline().decode("ascii", errors="ignore").strip()
            except Exception:
                time.sleep(0.05)
                continue
            if not line:
                continue
            if line.startswith("S:"):
                try:
                    data = json.loads(line[2:])
                except json.JSONDecodeError:
                    continue
                with self._lock:
                    self._latest = data
                    self._latest_ts = time.time()
                    self._history.append(data)
            elif line.startswith("R:"):
                # ack ou notif speciale (R:OBSTACLE, R:READY)
                try:
                    self._ack_q.put_nowait(line)
                except Exception:
                    pass

    # === API publique ===

    def send(self, cmd, timeout=1.0):
        # envoie cmd + '\n', attend une ligne R:* dans la queue
        # retourne (ok: bool, response: str)
        if not self._ser:
            return False, "not_open"
        # vide le backlog d'acks anciens
        while not self._ack_q.empty():
            try: self._ack_q.get_nowait()
            except Empty: break
        try:
            self._ser.write((cmd + "\n").encode("ascii"))
            self._ser.flush()
        except serial.SerialException as e:
            return False, f"write_err:{e}"
        try:
            resp = self._ack_q.get(timeout=timeout)
        except Empty:
            return False, "timeout"
        return resp.startswith("R:OK") or resp == "R:PONG", resp

    def get_state(self):
        # retourne un snapshot du dernier S:{...} + age en secondes
        with self._lock:
            return dict(self._latest), (time.time() - self._latest_ts) if self._latest_ts else None

    def get_ultrasound_cm(self):
        # raccourci pratique pour le brain
        with self._lock:
            return self._latest.get("u")