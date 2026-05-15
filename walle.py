#!/usr/bin/env python3
# walle.py - Orchestrateur WALL-E
# v2.0 : backend Ollama 100% offline + STT
# v2.1 : pseudonymisation - default user lu dynamiquement
# v2.3 : Phase 8.4 - lance VisionThread et branche face_q sur le brain
# v2.4 : Phase 8.3 reste - lance AudioThread (TTS + filtre robot)
# v2.4 Phase 17 : init hardware (ArduinoBridge + ToFSensors + Motors) attache a WORLD,
#                 avec --no-hardware pour tester en local sans Mega.
# v2.5 : pre-warm Ollama au boot (eteint P2 cold start ~57s, voir brain/prewarm.py).
#        OLLAMA_TIMEOUT bumpe a 180s pour marge sur appels gros contexte.

import argparse
import logging
import threading
import time
from queue import Queue, Empty

from dotenv import load_dotenv
load_dotenv()

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("walle")

from brain.agent import BrainThread
from brain.identity import Identity, parse_prefix
from brain.world_state import WORLD
from brain.prewarm import warmup_ollama   # v2.5 : evite cold start 57s sur 1er appel brain


def print_welcome(current_user, stt_enabled, vision_enabled, tts_enabled, hw_state):
    print()
    print("=" * 60)
    title = "  WALL-E reveille - v2.5 (Ollama offline + pre-warm, multi-user)"
    if stt_enabled:    title += " + STT"
    if vision_enabled: title += " + Vision"
    if tts_enabled:    title += " + Voix"
    print(title)
    print(f"  Backend : {config.LLM_BACKEND} / {config.OLLAMA_MODEL}")
    print(f"  Host    : {config.OLLAMA_HOST}")
    age_str = f", {current_user.age} ans" if current_user.age else ""
    print(f"  Locuteur courant : {current_user.display_name} ({current_user.role}{age_str})")
    # v2.4 : etat hardware physique
    print(f"  Hardware : Arduino={hw_state['arduino']}  ToF={hw_state['tof']}  Motors={hw_state['motors']}")
    print()
    print("  Commandes (clavier) :")
    print("    [user_id] bonjour...   changer de locuteur et continuer la phrase")
    print("    /who                   qui parle actuellement ?")
    print("    /users                 liste des users connus")
    print("    /reset                 efface la conv du locuteur courant")
    print("    /quit, Ctrl+C          sortir")
    if stt_enabled:
        print("  Micro actif : tu peux aussi parler (FR, pause ~1s pour valider)")
    if vision_enabled:
        print("  Camera active : WALL-E adapte son ton selon ton expression")
    if tts_enabled:
        print("  Voix active : WALL-E te repond en voix robot")
    print("=" * 60)
    print()


def keyboard_worker(user_in_q, stop_event):
    while not stop_event.is_set():
        try:
            line = input()
        except EOFError:
            break
        line = line.strip()
        if line:
            try:
                user_in_q.put_nowait(("keyboard", line))
            except Exception:
                pass


def init_hardware(no_hardware: bool):
    """v2.4 Phase 17 : ouvre Arduino + capteurs + Motors et attache a WORLD.

    Tout est tolerant aux pannes : si l'Arduino n'est pas branche, on tourne en
    mode degrade (les tools get_distances/move retourneront 'robot pas pret'
    cote agent, qui transmet poliment au LLM).
    """
    state = {"arduino": "OFF", "tof": "OFF", "motors": "OFF"}
    arduino = None
    tof = None
    motors = None

    if no_hardware:
        logger.info("Mode --no-hardware : pas d'init Arduino/capteurs/motors")
        return arduino, tof, motors, state

    # 1. Arduino bridge (port serie partage)
    try:
        from modules.sensors_arduino import ArduinoBridge
        arduino = ArduinoBridge()
        arduino.open()
        # ping pour valider que le firmware repond
        ok, resp = arduino.send("PING", timeout=2.0)
        if ok:
            logger.info("ArduinoBridge OK (%s) -> %s", config.SERIAL_PORT, resp)
            state["arduino"] = "ON"
        else:
            logger.warning("ArduinoBridge ouvert mais PING KO : %s", resp)
            state["arduino"] = "OPEN_NO_PONG"
    except Exception as e:
        logger.error("ArduinoBridge KO (%s) : %s", config.SERIAL_PORT, e)
        arduino = None

    # 2. ToF (peut tourner sans Arduino : c'est I2C natif Pi)
    try:
        from modules.sensors_tof import ToFSensors
        tof = ToFSensors()
        # init paresseuse : on ne touche pas au bus tant que personne n'appelle
        logger.info("ToFSensors instancie (init paresseuse au 1er get_distances)")
        state["tof"] = "READY"
    except Exception as e:
        logger.warning("ToFSensors import KO (probable hors Pi) : %s", e)
        tof = None

    # 3. Motors (necessite Arduino)
    if arduino is not None:
        try:
            from modules.motors import Motors
            motors = Motors(arduino)
            logger.info("Motors pret (Mecanum 4 roues, duty cap boot=%d%%)",
                        config.DUTY_BOOT_MAX)
            state["motors"] = "ON"
        except Exception as e:
            logger.error("Motors init KO : %s", e)
            motors = None

    WORLD.attach(tof=tof, arduino=arduino, motors=motors)
    if WORLD.is_ready():
        logger.info("WORLD attache : tools physiques disponibles pour le brain")
    else:
        logger.warning("WORLD partiel : tools get_distances/move repondront en mode degrade")

    return arduino, tof, motors, state


def shutdown_hardware(arduino, tof, motors):
    # ordre : moteurs OFF AVANT de fermer la liaison serie (safety)
    if motors is not None:
        try:
            motors.stop()
            logger.info("Motors stoppes")
        except Exception as e:
            logger.warning("Motors stop KO : %s", e)
    if arduino is not None:
        try:
            arduino.close()
            logger.info("ArduinoBridge ferme")
        except Exception as e:
            logger.warning("ArduinoBridge close KO : %s", e)
    if tof is not None:
        try:
            tof.close()
            logger.info("ToFSensors ferme")
        except Exception as e:
            logger.warning("ToFSensors close KO : %s", e)


def main():
    default_user = getattr(config, "DEFAULT_USER", "parent_1")

    parser = argparse.ArgumentParser(description="WALL-E v2.5 multi-user + STT + Vision + TTS")
    parser.add_argument("--user", type=str, default=default_user,
                        help=f"Locuteur par defaut (defaut : {default_user})")
    parser.add_argument("--no-stt", action="store_true",
                        help="Desactive le STT meme si config.STT_ENABLED=True")
    parser.add_argument("--no-vision", action="store_true",
                        help="Desactive la vision (camera + emotion)")
    parser.add_argument("--no-tts", action="store_true",
                        help="Desactive la voix (TTS + filtre robot)")
    parser.add_argument("--no-robot-filter", action="store_true",
                        help="Garde le TTS mais sans le filtre robot (voix Hortense brute)")
    # v2.4 Phase 17 : flag dev pour tourner sans Arduino branche
    parser.add_argument("--no-hardware", action="store_true",
                        help="Desactive Arduino + capteurs ToF + motors (test sans hardware)")
    # v2.5 : skip pre-warm pour dev rapide (si Ollama deja chaud d'une session precedente)
    parser.add_argument("--no-prewarm", action="store_true",
                        help="Skip le pre-warm Ollama (utile si modele deja en RAM)")
    args = parser.parse_args()

    # v2.5 : Pre-warm Ollama AVANT toute init hardware/threads.
    # Cold load qwen2.5:7b ~57s sur Pi 5, sinon 1er appel brain timeout.
    # keep_alive=-1 -> reste chaud pour toute la session.
    if not args.no_prewarm:
        if not warmup_ollama():
            logger.warning("Ollama prewarm KO -> brain demarre en degraded, 1er appel risque 60s+")

    current_identity = Identity.from_user_id(args.user)
    if current_identity.user_id == "unknown":
        first_user = next(iter(config.USERS.keys()), default_user)
        print(f"ATTENTION : user '{args.user}' inconnu, fallback sur '{first_user}'")
        current_identity = Identity.from_user_id(first_user)

    brain_in_q = Queue(maxsize=20)
    brain_out_q = Queue(maxsize=20)
    user_in_q = Queue(maxsize=20)
    face_q = Queue(maxsize=20)
    audio_q = Queue(maxsize=20)
    stop_event = threading.Event()

    # === Hardware - Phase 17 v2.4 (avant le brain pour que WORLD.is_ready() soit correct au boot brain) ===
    arduino, tof, motors, hw_state = init_hardware(args.no_hardware)

    # === VisionThread (Phase 2 + Phase 8.4) ===
    vision_thread = None
    vision_enabled = not args.no_vision
    if vision_enabled:
        try:
            from modules.vision import VisionThread
            vision_thread = VisionThread(
                face_q=face_q,
                stop_event=stop_event,
            )
            vision_thread.start()
            logger.info("VisionThread demarre")
        except Exception as e:
            logger.error(f"VisionThread non demarre : {e}")
            vision_enabled = False
            face_q = None

    # === BrainThread ===
    brain = BrainThread(brain_in_q, brain_out_q, stop_event,
                        face_q=face_q)
    brain.start()

    # === AudioThread (Phase 8.3 reste) ===
    audio_thread = None
    tts_enabled = getattr(config, "TTS_ENABLED", True) and not args.no_tts
    if tts_enabled:
        try:
            from modules.audio import AudioThread
            audio_thread = AudioThread(
                audio_q=audio_q,
                stop_event=stop_event,
                robot_filter=not args.no_robot_filter,
            )
            audio_thread.start()
        except Exception as e:
            logger.error(f"AudioThread non demarre : {e}")
            tts_enabled = False

    # === STT ===
    stt_thread = None
    stt_enabled = config.STT_ENABLED and not args.no_stt
    if stt_enabled:
        try:
            from modules.stt import STTThread
            stt_thread = STTThread(
                out_q=user_in_q,
                stop_event=stop_event,
                language=config.STT_LANGUAGE,
                sample_rate=config.STT_SAMPLE_RATE,
                device=config.STT_DEVICE,
                silence_threshold=config.STT_SILENCE_THRESHOLD,
                silence_duration=config.STT_SILENCE_DURATION,
                max_phrase_duration=config.STT_MAX_PHRASE,
            )
            stt_thread.start()
        except Exception as e:
            logger.error(f"STT non demarre : {e}")
            stt_enabled = False

    # === Clavier ===
    kb_thread = threading.Thread(
        target=keyboard_worker, args=(user_in_q, stop_event),
        daemon=True, name="KeyboardThread",
    )
    kb_thread.start()

    print_welcome(current_identity, stt_enabled, vision_enabled, tts_enabled, hw_state)

    try:
        while not stop_event.is_set():
            try:
                source, line = user_in_q.get(timeout=0.5)
            except Empty:
                continue

            label = "[voix]" if source == "voice" else "[clavier]"
            print(f"\n{current_identity.display_name} {label} > {line}")

            low = line.lower()
            if low in ("/quit", "/exit", "/q"):
                break
            if low == "/who":
                age_str = f", {current_identity.age} ans" if current_identity.age else ""
                print(f"  -> {current_identity.display_name} ({current_identity.user_id}, "
                      f"{current_identity.role}{age_str})")
                continue
            if low == "/users":
                for uid, info in config.USERS.items():
                    print(f"  - [{uid}] {info['display_name']} ({info['role']})")
                print("  - [unknown] voix non identifiee")
                continue
            if low == "/reset":
                brain.reset_history(current_identity.user_id)
                print(f"  -> conv de {current_identity.display_name} reinitialisee")
                continue
            # v2.4 : raccourci debug pour verifier le hardware sans passer par le LLM
            if low == "/sensors":
                d = WORLD.get_distances()
                print(f"  -> {d}")
                continue

            prefix_user, clean_text = parse_prefix(line)
            if prefix_user:
                new_identity = Identity.from_user_id(prefix_user)
                if new_identity.user_id == "unknown" and prefix_user != "unknown":
                    print(f"  -> [{prefix_user}] inconnu, traite comme voix non identifiee")
                current_identity = new_identity
                line = clean_text
                if not line:
                    age_str = f", {current_identity.age} ans" if current_identity.age else ""
                    print(f"  -> locuteur courant : {current_identity.display_name}{age_str}")
                    continue

            brain_in_q.put((current_identity.user_id, line))
            reply_uid, reply = brain_out_q.get()

            # Affichage texte
            print(f"\nWALL-E > {reply}\n")

            # Envoi TTS + attente fin de la lecture pour eviter l'echo
            if tts_enabled and audio_thread:
                try:
                    audio_q.put_nowait(reply)
                except Exception as e:
                    logger.warning("Audio queue pleine : %s", e)

                # Attendre que WALL-E ait fini de parler (anti-echo)
                time.sleep(0.5)
                while audio_thread.speaking_event.is_set() and not stop_event.is_set():
                    time.sleep(0.1)

                # Drainage de la queue STT : on jette tout ce qui a ete capte
                # pendant que WALL-E parlait (echo de sa propre voix)
                drained = 0
                while True:
                    try:
                        user_in_q.get_nowait()
                        drained += 1
                    except Empty:
                        break
                if drained > 0:
                    logger.info("Anti-echo : %d entree(s) STT droppee(s)", drained)

    except KeyboardInterrupt:
        print("\n[Ctrl+C]")

    print("Arret en cours...")
    stop_event.set()

    # v2.4 : on coupe le hardware AVANT les threads pour eviter qu'un brain en cours
    # n'envoie une commande moteur sur un port deja ferme
    shutdown_hardware(arduino, tof, motors)

    brain.join(timeout=3)
    if stt_thread:
        stt_thread.join(timeout=3)
    if vision_thread:
        vision_thread.join(timeout=3)
    if audio_thread:
        audio_thread.join(timeout=3)
    print("A bientot !")


if __name__ == "__main__":
    main()