# brain/world_state.py - singleton d'etat physique partage par les tools LLM
# v2.4 : NEW. Le BrainThread n'a rien a savoir de l'archi capteurs : il appelle
# WORLD.get_distances() / WORLD.move(...) et c'est tout.

import threading


class WorldState:
    # Tient les references aux objets hardware. Initialise depuis walle.py au boot.
    # Les tools (brain/tools.py) accedent via WORLD (instance module).

    def __init__(self):
        self._lock = threading.Lock()
        self._tof = None        # modules.sensors_tof.ToFSensors
        self._arduino = None    # modules.sensors_arduino.ArduinoBridge
        self._motors = None     # modules.motors.Motors

    def attach(self, tof=None, arduino=None, motors=None):
        # injection de dependances : on cable au boot, pas a l'import
        with self._lock:
            if tof is not None:      self._tof = tof
            if arduino is not None:  self._arduino = arduino
            if motors is not None:   self._motors = motors

    def is_ready(self) -> bool:
        return self._arduino is not None  # minimum vital pour move()

    # === API exposee aux tools ===

    def get_distances(self) -> dict:
        # v2.5 : 2 capteurs ToF (G/D) + ultrason avant. None si capteur HS.
        tof = self._tof.read_all() if self._tof else {"left": None, "right": None}
        us = None
        age = None
        if self._arduino:
            state, age = self._arduino.get_state()
            us = state.get("u") if state else None
        return {
            "tof_left_cm":          tof.get("left"),
            "tof_right_cm":         tof.get("right"),
            "ultrasound_front_cm":  us,
            "sensor_age_s":         round(age, 2) if age is not None else None,
        }

    def move(self, direction: str, intensity: int = 50) -> tuple[bool, str]:
        # direction in {forward, backward, strafe_left, strafe_right,
        #               rotate_left, rotate_right, stop}
        if self._motors is None:
            return False, "motors_not_initialized"
        return self._motors.move(direction, intensity)


# Instance singleton importable directement
WORLD = WorldState()