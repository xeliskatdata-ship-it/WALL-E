# modules/motors.py - kinematics Mecanum + envoi commandes via ArduinoBridge
# v2.4 : refactor majeur. N'ouvre PLUS son propre port serie : passe par
# ArduinoBridge (sensors_arduino.py) pour eviter le conflit avec le reader
# de capteurs qui lit le meme port.
#
# Convention Mecanum X-config :
#   vy > 0  -> avance        | vy < 0  -> recule
#   vx > 0  -> strafe droite | vx < 0  -> strafe gauche
#   omega > 0 -> rotation antihoraire (gauche)
#
#   v_FL = vy + vx - omega
#   v_FR = vy - vx + omega
#   v_BL = vy - vx - omega
#   v_BR = vy + vx + omega

import logging

import config

logger = logging.getLogger("walle.motors")


_DIRECTIONS = {
    "forward":       (0,  +1, 0),
    "backward":      (0,  -1, 0),
    "strafe_right":  (+1,  0, 0),
    "strafe_left":   (-1,  0, 0),
    "rotate_left":   (0,   0, +1),    # antihoraire
    "rotate_right":  (0,   0, -1),    # horaire
    "stop":          (0,   0, 0),
}


class Motors:
    # Wrapper haut-niveau. L'agent appelle motors.move("forward", 50) et c'est tout.

    def __init__(self, arduino_bridge):
        self.arduino = arduino_bridge
        self._duty_cap = config.DUTY_BOOT_MAX

    def move(self, direction: str, intensity: int = 50) -> tuple[bool, str]:
        if direction not in _DIRECTIONS:
            return False, f"direction inconnue : {direction}"
        intensity = max(0, min(100, int(intensity)))
        if direction == "stop" or intensity == 0:
            return self._send_stop()

        vx_u, vy_u, om_u = _DIRECTIONS[direction]
        vx = vx_u * intensity
        vy = vy_u * intensity
        om = om_u * intensity

        # mix Mecanum X
        fl = _clip(vy + vx - om)
        fr = _clip(vy - vx + om)
        bl = _clip(vy - vx - om)
        br = _clip(vy + vx + om)

        cmd = f"MOTORS {fl} {fr} {bl} {br}"
        ok, resp = self.arduino.send(cmd, timeout=1.0)
        if not ok:
            logger.warning("MOTORS echec : %s", resp)
            # cas particulier : Arduino a refuse pour obstacle, on remonte clairement
            if resp == "R:OBSTACLE":
                return False, "obstacle_detected"
            return False, resp
        return True, f"ok dir={direction} i={intensity}"

    def stop(self):
        return self._send_stop()

    def set_duty_cap(self, cap: int) -> tuple[bool, str]:
        # debridage runtime apres validation : ex set_duty_cap(80) une fois confirme stable
        cap = max(0, min(100, int(cap)))
        ok, resp = self.arduino.send(f"DUTY {cap}", timeout=1.0)
        if ok:
            self._duty_cap = cap
        return ok, resp

    def _send_stop(self):
        ok, resp = self.arduino.send("STOP", timeout=1.0)
        return ok, resp


def _clip(v):
    return max(-100, min(100, int(round(v))))