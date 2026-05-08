# tests/test_sensors.py - tests bring-up capteurs WALL-E
# v2.4 : NEW.
#
# Modes :
#   --dry           : pure logique, pas de hardware, OK sur Windows
#   --live-tof      : lecture reelle 3 VL53L1X (sur Pi uniquement)
#   --live-arduino  : PING + lecture push S:{...} (Pi + Mega flashe)

import argparse
import sys
import time


def test_dry():
    # On verifie juste que les modules s'importent et que les classes s'instancient
    print("[DRY] import config...", end=" ")
    import config
    print("OK")
    assert config.SERIAL_PORT == "/dev/ttyACM0"
    assert config.OLLAMA_MODEL == "qwen2.5:7b"
    assert config.TCA_ADDRESS == 0x70
    assert set(config.TOF_CHANNELS.keys()) == {"left", "center", "right"}
    print("[DRY] config valeurs attendues : OK")

    print("[DRY] import ToFSensors...", end=" ")
    from modules.sensors_tof import ToFSensors
    tof = ToFSensors()
    assert not tof._initialized   # init paresseuse
    print("OK")

    print("[DRY] import ArduinoBridge...", end=" ")
    from modules.sensors_arduino import ArduinoBridge
    br = ArduinoBridge()
    assert br._ser is None        # pas ouvert
    print("OK")

    print("\n[DRY] all green")


def test_live_tof():
    from modules.sensors_tof import ToFSensors
    tof = ToFSensors()
    print("[ToF] init + 5 cycles de lecture")
    for i in range(5):
        d = tof.read_all()
        print(f"  cycle {i}: L={d['left']} C={d['center']} R={d['right']}")
        time.sleep(0.2)
    tof.close()
    print("[ToF] fin")


def test_live_arduino():
    from modules.sensors_arduino import ArduinoBridge
    br = ArduinoBridge()
    print("[Arduino] open serial...", end=" ")
    br.open()
    print("OK")

    print("[Arduino] PING...", end=" ")
    ok, resp = br.send("PING", timeout=2.0)
    print(f"{resp} ({'OK' if ok else 'FAIL'})")

    print("[Arduino] lecture push capteurs 5s...")
    t0 = time.time()
    while time.time() - t0 < 5.0:
        state, age = br.get_state()
        if state:
            print(f"  u={state.get('u')}cm  ax={state.get('ax')}  gz={state.get('gz')}  age={age:.2f}s")
        time.sleep(0.5)

    br.close()
    print("[Arduino] fin")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true")
    p.add_argument("--live-tof", action="store_true")
    p.add_argument("--live-arduino", action="store_true")
    args = p.parse_args()

    if args.dry: test_dry()
    elif args.live_tof: test_live_tof()
    elif args.live_arduino: test_live_arduino()
    else:
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()