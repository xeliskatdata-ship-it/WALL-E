# brain/prewarm.py - charge le modele Ollama en RAM au boot
# v2.5 : eteint P2 backlog (timeout 60s systematique sur cold load qwen2.5:7b 4.7GB).
# A lancer AVANT walle.py (ou via subprocess au tout debut de walle.py).

import logging
import time
import requests

import config

logger = logging.getLogger("prewarm")

# Cold load qwen2.5:7b sur Pi 5 observe ~30-90s. Marge confortable a 300s.
PREWARM_TIMEOUT = 300


def warmup_ollama():
    # Force le chargement modele via 1 appel minimal (1 token).
    # keep_alive=-1 -> reste charge jusqu'au prochain `ollama serve` restart
    # ou pression memoire. Sur Pi 5 16GB : ~5GB occupes, marge OK.
    url = f"{config.OLLAMA_HOST.rstrip('/')}/api/chat"
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "keep_alive": -1,                  # garde le modele en RAM indefiniment
        "options": {"num_predict": 1},     # 1 token, reponse osef
    }

    logger.info(f"[prewarm] chargement {config.OLLAMA_MODEL} en RAM via {url}...")
    t0 = time.perf_counter()
    try:
        r = requests.post(url, json=payload, timeout=PREWARM_TIMEOUT)
        r.raise_for_status()
        elapsed = time.perf_counter() - t0
        logger.info(f"[prewarm] modele charge en {elapsed:.1f}s - OK")
        return True

    except requests.exceptions.ConnectionError:
        # Ollama pas demarre / port ferme
        logger.error(f"[prewarm] connexion refusee sur {url} - `ollama serve` lance ?")
        return False

    except requests.exceptions.ReadTimeout:
        elapsed = time.perf_counter() - t0
        logger.error(f"[prewarm] TIMEOUT apres {elapsed:.1f}s - brain partira en degraded")
        return False

    except Exception as e:
        elapsed = time.perf_counter() - t0
        logger.error(f"[prewarm] echec ({elapsed:.1f}s) : {e}")
        return False


if __name__ == "__main__":
    # Permet `python -m brain.prewarm` en standalone (script bash wrapper, systemd, etc.)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )
    ok = warmup_ollama()
    exit(0 if ok else 1)
