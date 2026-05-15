# models/download_models.py - DL idempotent des modeles ONNX pour vision.py
# A lancer une fois apres clone du repo (ou au setup d'un nouveau venv).
# Les .onnx sont gitignored (cf .gitignore), on les recupere a la demande.

import hashlib
import sys
import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).parent

# YuNet face detector - OpenCV Zoo, ~230 KB, license MIT
YUNET = {
    "url": "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "filename": "face_detection_yunet_2023mar.onnx",
    "sha256": None,  # check optionnel, le repo opencv_zoo est stable
}

# FER+ emotion classifier - ONNX Model Zoo, ~34 MB, license MIT
FERPLUS = {
    "url": "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/emotion_ferplus/model/emotion-ferplus-8.onnx",
    "filename": "emotion-ferplus-8.onnx",
    "sha256": None,
}

MODELS = [YUNET, FERPLUS]


def _download(url, dest):
    # urllib stdlib pour eviter de rajouter requests dans les deps
    print(f"  -> {url}")
    with urllib.request.urlopen(url, timeout=30) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(8192)
            if not chunk: break
            f.write(chunk)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    MODELS_DIR.mkdir(exist_ok=True)
    for m in MODELS:
        dest = MODELS_DIR / m["filename"]
        if dest.exists():
            size_mb = dest.stat().st_size / 1024 / 1024
            print(f"[OK]   {m['filename']} ({size_mb:.1f} MB) - deja la")
            continue
        print(f"[DL]   {m['filename']}")
        try:
            _download(m["url"], dest)
            size_mb = dest.stat().st_size / 1024 / 1024
            print(f"       Telecharge ({size_mb:.1f} MB)")
            if m["sha256"]:
                got = _sha256(dest)
                if got != m["sha256"]:
                    print(f"[FAIL] sha256 KO : attendu {m['sha256']}, recu {got}")
                    dest.unlink()
                    sys.exit(1)
        except Exception as e:
            print(f"[FAIL] {m['filename']} : {e}")
            if dest.exists(): dest.unlink()
            sys.exit(1)
    print("\nDone. Modeles dans :", MODELS_DIR.resolve())


if __name__ == "__main__":
    main()
