# modules/sensors_tof.py - lecture des 3 VL53L1X via TCA9548A
# v2.4 : NEW. 3 capteurs partagent l'adresse I2C 0x29, mux obligatoire.

import time
import config


class ToFSensors:
    # Init paresseuse (au 1er read_all) -> permet l'import sans hardware (mode --dry).

    def __init__(self):
        self._initialized = False
        self._sensors = {}   # {"left": vl53, "center": vl53, "right": vl53}
        self._mux = None

    def _init_hw(self):
        # Imports differes : sur Pi uniquement, et evite de planter --dry sur Windows
        import board
        import busio
        import adafruit_tca9548a
        import adafruit_vl53l1x

        i2c = busio.I2C(board.SCL, board.SDA)
        self._mux = adafruit_tca9548a.TCA9548A(i2c, address=config.TCA_ADDRESS)

        for name, ch in config.TOF_CHANNELS.items():
            try:
                vl = adafruit_vl53l1x.VL53L1X(self._mux[ch])
                vl.distance_mode = 2  # long range
                vl.timing_budget = config.TOF_TIMING_BUDGET_MS
                vl.start_ranging()
                self._sensors[name] = vl
            except Exception as e:
                # un capteur HS ne doit pas couler les 2 autres
                print(f"[ToF] capteur {name} ch{ch} indisponible : {e}")
                self._sensors[name] = None

        self._initialized = True

    def read_all(self):
        # retourne {"left": cm|None, "center": cm|None, "right": cm|None}
        if not self._initialized:
            self._init_hw()
        out = {}
        for name, vl in self._sensors.items():
            if vl is None:
                out[name] = None
                continue
            try:
                if vl.data_ready:
                    out[name] = vl.distance   # deja en cm
                    vl.clear_interrupt()
                else:
                    # pas pret cette frame, on garde None plutot que stale
                    out[name] = None
            except Exception:
                out[name] = None
        return out

    def close(self):
        for vl in self._sensors.values():
            if vl is not None:
                try: vl.stop_ranging()
                except Exception: pass