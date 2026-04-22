# modules/motors.py — Thread communication série Pi → Arduino
# Lit motor_q, envoie les commandes, attend ACK, applique le lissage.

import time
import threading
import logging

import serial

import config

logger = logging.getLogger("walle.motors")


class MotorsThread(threading.Thread):
    """Thread dédié à la communication série avec l'Arduino.
    
    Lit les commandes depuis motor_q et les envoie via UART.
    Applique un filtre passe-bas sur les angles tête pour éviter les saccades.
    """

    def __init__(self, motor_q, stop_event=None):
        super().__init__(name="MotorsThread", daemon=True)
        self.motor_q = motor_q
        self.stop_event = stop_event or threading.Event()
        self._ser = None
        self._connected = False

        # État interne pour le lissage (tête uniquement)
        self._smooth_pan = 90.0
        self._smooth_tilt = 90.0
        self._last_obstacle_dist = -1.0

    # ---------------------------------------------------------------
    # Connexion série
    # ---------------------------------------------------------------
    def _connect(self):
        """Tente d'ouvrir le port série. Retente toutes les 2s si échec."""
        while not self.stop_event.is_set():
            try:
                self._ser = serial.Serial(
                    port=config.SERIAL_PORT,
                    baudrate=config.BAUD_RATE,
                    timeout=config.WATCHDOG_TIMEOUT,
                    write_timeout=0.1,
                )
                # Attendre le "READY" de l'Arduino après reset
                time.sleep(2.0)
                self._ser.reset_input_buffer()

                # Test de connexion
                response = self._send_raw("PING")
                if response and "PONG" in response:
                    self._connected = True
                    logger.info("Arduino connecté sur %s @ %d baud",
                                config.SERIAL_PORT, config.BAUD_RATE)
                    return True
                else:
                    logger.warning("Arduino trouvé mais PING échoué (réponse: %s)", response)
                    self._ser.close()

            except serial.SerialException as e:
                logger.warning("Port série %s indisponible : %s — retry dans 2s",
                               config.SERIAL_PORT, e)

            time.sleep(2.0)

        return False

    # ---------------------------------------------------------------
    # Envoi bas niveau
    # ---------------------------------------------------------------
    def _send_raw(self, cmd):
        """Envoie une commande brute et retourne la réponse (ou None)."""
        if not self._ser or not self._ser.is_open:
            return None
        try:
            self._ser.write(f"{cmd}\n".encode("ascii"))
            self._ser.flush()
            response = self._ser.readline().decode("ascii").strip()
            return response
        except (serial.SerialException, serial.SerialTimeoutException) as e:
            logger.error("Erreur série sur commande '%s' : %s", cmd, e)
            self._connected = False
            return None

    def send_command(self, cmd):
        """Envoie une commande et vérifie l'ACK 'OK'."""
        response = self._send_raw(cmd)
        if response == "OK":
            return True
        elif response:
            logger.warning("Réponse inattendue pour '%s' : '%s'", cmd, response)
            return "ERR" not in response
        else:
            logger.error("Pas de réponse pour '%s' (timeout)", cmd)
            return False

    # ---------------------------------------------------------------
    # Lissage passe-bas (tête uniquement)
    # ---------------------------------------------------------------
    def _smooth_head(self, cmd):
        """Applique un filtre passe-bas sur HP/HT pour un mouvement fluide.
        Retourne la commande avec l'angle lissé."""
        alpha = config.SMOOTHING_ALPHA

        if cmd.startswith("HP"):
            raw_angle = int(cmd[2:])
            self._smooth_pan = alpha * raw_angle + (1 - alpha) * self._smooth_pan
            return f"HP{int(self._smooth_pan)}"

        elif cmd.startswith("HT"):
            raw_angle = int(cmd[2:])
            self._smooth_tilt = alpha * raw_angle + (1 - alpha) * self._smooth_tilt
            return f"HT{int(self._smooth_tilt)}"

        # Pas un mouvement tête → retourner tel quel
        return cmd

    # ---------------------------------------------------------------
    # Boucle principale
    # ---------------------------------------------------------------
    def run(self):
        logger.info("Démarrage du thread motors")

        if not self._connect():
            logger.error("Impossible de se connecter à l'Arduino, thread arrêté.")
            return

        try:
            while not self.stop_event.is_set():
                # Lire la queue (timeout 100ms pour permettre le stop)
                try:
                    item = self.motor_q.get(timeout=0.1)
                except Exception:
                    continue

                cmd = item if isinstance(item, str) else item.get("cmd", "")
                if not cmd:
                    continue

                # Lissage pour les mouvements de tête
                if cmd.startswith("HP") or cmd.startswith("HT"):
                    cmd = self._smooth_head(cmd)

                # Envoyer
                success = self.send_command(cmd)

                if not success and not self._connected:
                    # Tentative de reconnexion
                    logger.info("Reconnexion série en cours...")
                    self._connect()

        except Exception as e:
            logger.exception("Erreur dans le thread motors : %s", e)
        finally:
            # Remettre en position neutre avant de fermer
            if self._ser and self._ser.is_open:
                self._send_raw("IDLE")
                self._ser.close()
            logger.info("Thread motors arrêté")

    # ---------------------------------------------------------------
    # API publique
    # ---------------------------------------------------------------
    @property
    def connected(self):
        return self._connected

    def get_distance(self):
        """Interroge le capteur ultrason. Retourne la distance en cm ou -1."""
        response = self._send_raw("DIST")
        if response and response.startswith("DIST:"):
            try:
                return float(response.split(":")[1])
            except ValueError:
                return -1.0
        return -1.0


# ---------------------------------------------------------------
# Utilitaire : calcul des angles tête depuis les coordonnées visage
# ---------------------------------------------------------------
def compute_head_angles(cx, cy, pan_range=45, tilt_range=30):
    """Convertit le centre normalisé du visage [-1, +1] en angles servo.
    
    Args:
        cx: position horizontale normalisée (-1 = gauche, +1 = droite)
        cy: position verticale normalisée (-1 = haut, +1 = bas)
        pan_range: amplitude max en degrés autour de 90°
        tilt_range: amplitude max en degrés autour de 90°
    
    Returns:
        (pan, tilt) : angles servo entre 0 et 180
    """
    # Inverser le pan : visage à droite → tête tourne à droite (angle diminue)
    pan  = int(90 - cx * pan_range)
    tilt = int(90 + cy * tilt_range)

    # Clamp 0–180
    pan  = max(0, min(180, pan))
    tilt = max(0, min(180, tilt))

    return pan, tilt