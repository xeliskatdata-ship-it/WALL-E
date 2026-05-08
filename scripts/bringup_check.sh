#!/usr/bin/env bash
# scripts/bringup_check.sh - validation pre-boot WALL-E sur Pi 5
# v2.4 : NEW. A lancer apres install Phase A/B, avant flash Arduino.

set -u

GREEN='\033[0;32m'
RED='\033[0;31m'
YELL='\033[0;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC}   $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; FAILS=$((FAILS+1)); }
warn() { echo -e "${YELL}[WARN]${NC} $1"; }

FAILS=0

echo "=== WALL-E bringup check ==="

# 1. Python version
PYV=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"; then
    ok "Python $PYV"
else
    fail "Python $PYV (>= 3.10 requis)"
fi

# 2. Ollama installe
if command -v ollama >/dev/null 2>&1; then
    ok "ollama installe ($(ollama --version 2>&1 | head -1))"
    if ollama list 2>/dev/null | grep -q "qwen2.5:7b"; then
        ok "qwen2.5:7b dispo"
    else
        fail "qwen2.5:7b absent  -> ollama pull qwen2.5:7b"
    fi
else
    fail "ollama non installe -> curl -fsSL https://ollama.com/install.sh | sh"
fi

# 3. Port serie Arduino
if [ -e /dev/ttyACM0 ]; then
    ok "/dev/ttyACM0 present"
else
    warn "/dev/ttyACM0 absent (Mega pas branche ?)"
fi

# 4. Groupe dialout
if id -nG "$USER" | grep -qw dialout; then
    ok "user $USER dans dialout"
else
    fail "user $USER pas dans dialout -> sudo usermod -a -G dialout $USER && relog"
fi

# 5. I2C bus 1
if command -v i2cdetect >/dev/null 2>&1; then
    if i2cdetect -y 1 2>/dev/null | grep -q "70"; then
        ok "TCA9548A detecte a 0x70"
    else
        warn "TCA9548A absent du scan i2c (pas grave si pas encore cable)"
    fi
else
    fail "i2cdetect absent -> sudo apt install i2c-tools"
fi

# 6. picamera2
if python3 -c "import picamera2" 2>/dev/null; then
    ok "picamera2 importable"
else
    fail "picamera2 manquant -> sudo apt install python3-picamera2"
fi

# 7. Camera physique
if command -v libcamera-hello >/dev/null 2>&1; then
    if libcamera-hello -t 100 --nopreview >/dev/null 2>&1; then
        ok "camera repond a libcamera-hello"
    else
        warn "libcamera-hello echec (camera pas branchee ou raspi-config camera off)"
    fi
fi

# 8. Throttling thermique / power
if command -v vcgencmd >/dev/null 2>&1; then
    THR=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)
    if [ "$THR" = "0x0" ]; then
        ok "vcgencmd throttled=0x0 (alim et thermique OK)"
    else
        fail "vcgencmd throttled=$THR (under-volt ou throttle thermique en cours)"
    fi
fi

# 9. Modules Python ToF
for mod in serial board busio adafruit_tca9548a adafruit_vl53l1x ollama chromadb; do
    if python3 -c "import $mod" 2>/dev/null; then
        ok "py module $mod"
    else
        fail "py module $mod absent -> pip install -r requirements.txt"
    fi
done

echo ""
if [ $FAILS -eq 0 ]; then
    echo -e "${GREEN}=== bringup check : tout vert ===${NC}"
    exit 0
else
    echo -e "${RED}=== bringup check : $FAILS erreur(s) ===${NC}"
    exit 1
fi