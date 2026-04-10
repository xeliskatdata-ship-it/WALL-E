#!/usr/bin/env python3
# tests/test_motors.py — Test Phase 3 : communication série + servos
#
# Usage :
#   python tests/test_motors.py --dry-run       → vérifie imports uniquement
#   python tests/test_motors.py --simulate       → simule le protocole sans Arduino
#   python tests/test_motors.py                  → test live avec Arduino branché
#   python tests/test_motors.py --arms           → test bras uniquement (Phase 6)
#   python tests/test_motors.py --port COM3      → override du port série
#
# En mode live, appuie sur Ctrl+C pour arrêter.

import sys
import os
import time
import argparse
import logging
from queue import Queue
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from modules.motors import MotorsThread, compute_head_angles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_motors")


# ---------------------------------------------------------------
# Dry run : imports uniquement
# ---------------------------------------------------------------
def test_dry_run():
    logger.info("=== MODE DRY-RUN ===")
    logger.info("Import config .............. OK")

    import serial
    logger.info("Import pyserial ............ OK (v%s)", serial.VERSION)

    from modules.motors import MotorsThread, compute_head_angles
    logger.info("Import modules/motors ...... OK")

    # Test compute_head_angles
    pan, tilt = compute_head_angles(0.0, 0.0)
    assert pan == 90 and tilt == 90, f"Centre attendu (90,90), obtenu ({pan},{tilt})"
    logger.info("compute_head_angles(0,0) ... OK → (90, 90)")

    pan, tilt = compute_head_angles(-1.0, -1.0)
    assert pan == 135 and tilt == 60, f"Attendu (135,60), obtenu ({pan},{tilt})"
    logger.info("compute_head_angles(-1,-1).. OK → (135, 60)")

    pan, tilt = compute_head_angles(1.0, 1.0)
    assert pan == 45 and tilt == 120, f"Attendu (45,120), obtenu ({pan},{tilt})"
    logger.info("compute_head_angles(1,1) ... OK → (45, 120)")

    # Test clamp
    pan, tilt = compute_head_angles(3.0, -3.0)
    assert 0 <= pan <= 180 and 0 <= tilt <= 180
    logger.info("compute_head_angles clamp .. OK")

    logger.info("")
    logger.info("✅ DRY-RUN RÉUSSI — Tous les imports et fonctions OK.")
    logger.info("   Branche un Arduino et relance sans --dry-run pour le test live.")


# ---------------------------------------------------------------
# Simulation : teste le protocole sans matériel
# ---------------------------------------------------------------
def test_simulate():
    logger.info("=== MODE SIMULATION (sans Arduino) ===")
    logger.info("Simule l'envoi de commandes et vérifie le format du protocole.")
    logger.info("")

    commands = [
        ("PING",   "Test connexion"),
        ("HP90",   "Tête centre"),
        ("HT90",   "Tête centre vertical"),
        ("HP45",   "Tête droite"),
        ("HP135",  "Tête gauche"),
        ("HT60",   "Tête vers le haut"),
        ("HT120",  "Tête vers le bas"),
        ("ALS10",  "Bras G épaule bas"),
        ("ALS120", "Bras G épaule levé"),
        ("ALR90",  "Bras G rotation neutre"),
        ("ALR40",  "Bras G rotation fermé"),
        ("ARS120", "Bras D épaule levé"),
        ("ARR140", "Bras D rotation fermé"),
        ("HUG",    "Macro câlin"),
        ("WAVE",   "Macro salut"),
        ("IDLE",   "Position neutre"),
        ("DIST",   "Lecture distance"),
    ]

    logger.info("%-10s %-30s %s", "COMMANDE", "DESCRIPTION", "FORMAT OK ?")
    logger.info("-" * 60)

    all_ok = True
    for cmd, desc in commands:
        # Vérifier le format
        valid = _validate_command_format(cmd)
        status = "✅" if valid else "❌"
        if not valid:
            all_ok = False
        logger.info("%-10s %-30s %s", cmd, desc, status)

    # Test séquence suivi de regard
    logger.info("")
    logger.info("--- Séquence suivi de regard (simulation) ---")
    positions = [
        (-0.8, 0.0, "Visage à gauche"),
        (-0.4, -0.2, "Visage centre-gauche, légèrement haut"),
        (0.0, 0.0, "Visage au centre"),
        (0.4, 0.3, "Visage centre-droit, légèrement bas"),
        (0.8, 0.0, "Visage à droite"),
    ]

    alpha = config.SMOOTHING_ALPHA
    smooth_pan, smooth_tilt = 90.0, 90.0

    for cx, cy, desc in positions:
        pan, tilt = compute_head_angles(cx, cy)
        # Simuler le lissage
        smooth_pan = alpha * pan + (1 - alpha) * smooth_pan
        smooth_tilt = alpha * tilt + (1 - alpha) * smooth_tilt
        logger.info("  cx=%.1f cy=%.1f → HP%d HT%d (lissé: HP%d HT%d) — %s",
                     cx, cy, pan, tilt, int(smooth_pan), int(smooth_tilt), desc)

    logger.info("")
    if all_ok:
        logger.info("✅ SIMULATION RÉUSSIE — Tous les formats de commande sont valides.")
    else:
        logger.error("❌ SIMULATION ÉCHOUÉE — Certains formats sont invalides.")


def _validate_command_format(cmd):
    """Vérifie qu'une commande respecte le protocole."""
    # Macros sans argument
    if cmd in ("PING", "HUG", "WAVE", "IDLE", "DIST"):
        return True

    # Commandes avec angle
    prefixes = {"HP": 2, "HT": 2, "ALS": 3, "ALR": 3, "ARS": 3, "ARR": 3}
    for prefix, length in prefixes.items():
        if cmd.startswith(prefix) and len(cmd) > length:
            try:
                angle = int(cmd[length:])
                return 0 <= angle <= 180
            except ValueError:
                return False

    return False


# ---------------------------------------------------------------
# Test live avec Arduino
# ---------------------------------------------------------------
def test_live(arms=False):
    logger.info("=== MODE LIVE (Arduino branché) ===")
    logger.info("Port : %s | Baud : %d", config.SERIAL_PORT, config.BAUD_RATE)
    logger.info("")

    motor_q = Queue(maxsize=20)
    stop_event = threading.Event()

    motors = MotorsThread(motor_q, stop_event)
    motors.start()

    # Attendre la connexion
    time.sleep(3)
    if not motors.connected:
        logger.error("❌ Arduino non connecté. Vérifie :")
        logger.error("   - Le câble USB est branché")
        logger.error("   - Le firmware baymax_servo.ino est flashé")
        logger.error("   - Le port %s est correct (ls /dev/ttyUSB* ou ls /dev/ttyACM*)",
                      config.SERIAL_PORT)
        stop_event.set()
        return

    logger.info("✅ Arduino connecté !")
    logger.info("")

    try:
        if arms:
            _test_sequence_arms(motor_q)
        else:
            _test_sequence_head(motor_q)

    except KeyboardInterrupt:
        logger.info("Ctrl+C détecté")

    finally:
        logger.info("Retour en position neutre...")
        motor_q.put("IDLE")
        time.sleep(2)
        stop_event.set()
        motors.join(timeout=3)
        logger.info("Test terminé.")


def _test_sequence_head(motor_q):
    """Séquence de test pour la tête (Phase 3)."""
    steps = [
        ("HP90",  "Centre", 1.0),
        ("HP45",  "Droite", 1.5),
        ("HP135", "Gauche", 1.5),
        ("HP90",  "Centre", 1.0),
        ("HT60",  "Haut", 1.5),
        ("HT120", "Bas", 1.5),
        ("HT90",  "Centre", 1.0),
        # Mouvement diagonal
        ("HP60",  "Diag haut-droite (pan)", 0.2),
        ("HT70",  "Diag haut-droite (tilt)", 1.5),
        ("HP120", "Diag bas-gauche (pan)", 0.2),
        ("HT110", "Diag bas-gauche (tilt)", 1.5),
        ("IDLE",  "Retour neutre", 1.5),
    ]

    logger.info("--- Test servos tête (Pan + Tilt) ---")
    _run_steps(motor_q, steps)
    logger.info("")
    logger.info("✅ Test tête terminé. Le mouvement était-il fluide ?")


def _test_sequence_arms(motor_q):
    """Séquence de test pour les bras (Phase 6)."""
    steps = [
        ("IDLE",   "Position neutre", 1.5),
        # Bras gauche
        ("ALS90",  "Bras G épaule mi-hauteur", 1.5),
        ("ALS120", "Bras G épaule levé", 1.5),
        ("ALR40",  "Bras G rotation fermé", 1.5),
        ("ALR90",  "Bras G rotation ouvert", 1.0),
        ("ALS10",  "Bras G épaule bas", 1.5),
        # Bras droit
        ("ARS90",  "Bras D épaule mi-hauteur", 1.5),
        ("ARS120", "Bras D épaule levé", 1.5),
        ("ARR140", "Bras D rotation fermé", 1.5),
        ("ARR90",  "Bras D rotation ouvert", 1.0),
        ("ARS10",  "Bras D épaule bas", 1.5),
        # Macros
        ("HUG",    "Macro CÂLIN", 3.0),
        ("IDLE",   "Retour neutre", 2.0),
        ("WAVE",   "Macro SALUT", 3.0),
        ("IDLE",   "Retour neutre", 1.5),
    ]

    logger.info("--- Test bras (4× DS3218) + macros ---")
    _run_steps(motor_q, steps)
    logger.info("")
    logger.info("✅ Test bras terminé.")


def _run_steps(motor_q, steps):
    for cmd, desc, wait in steps:
        logger.info("  → %-8s  %s", cmd, desc)
        motor_q.put(cmd)
        time.sleep(wait)


# ---------------------------------------------------------------
# Main
# ---------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Test Phase 3 — Motors Baymax")
    parser.add_argument("--dry-run", action="store_true",
                        help="Vérifie les imports sans Arduino")
    parser.add_argument("--simulate", action="store_true",
                        help="Simule le protocole sans matériel")
    parser.add_argument("--arms", action="store_true",
                        help="Test bras uniquement (Phase 6)")
    parser.add_argument("--port", type=str, default=None,
                        help="Override du port série (ex: COM3, /dev/ttyUSB0)")
    args = parser.parse_args()

    if args.port:
        config.SERIAL_PORT = args.port

    if args.dry_run:
        test_dry_run()
    elif args.simulate:
        test_simulate()
    else:
        test_live(arms=args.arms)


if __name__ == "__main__":
    main()