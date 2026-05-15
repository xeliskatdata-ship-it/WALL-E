#!/usr/bin/env python3
"""Script de calibration vision Phase 8.4 v2.

Mesure les valeurs des nouvelles fonctions normalisees pendant 15s
en mimant 5 emotions, puis affiche les statistiques pour ajuster les seuils.

Usage : python tmp/calibrate_emotion.py
"""

import sys, time
sys.path.insert(0, '.')

import cv2
import numpy as np
import mediapipe as mp
import config

# On importe les NOUVELLES fonctions de vision.py v2
from modules.vision import (
    _compute_mar, _compute_smile_score, _compute_ear,
    _compute_brow_squeeze, _compute_brow_drop,
)


def main():
    cap = cv2.VideoCapture(config.CAMERA_INDEX)
    if not cap.isOpened():
        print("Camera KO - verifie que personne d'autre ne l'utilise (WALL-E doit etre ferme)")
        return

    mp_face = mp.solutions.face_mesh
    fm = mp_face.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=config.VISION_MIN_CONFIDENCE,
    )

    print("Lance ! Mime des emotions pendant 15 secondes :")
    print("  - 0-3s : visage NEUTRE")
    print("  - 3-6s : SOURIRE FRANC")
    print("  - 6-9s : TRISTE bouche tombante + sourcils baisses")
    print("  - 9-12s : DOULEUR yeux plisses + sourcils fronces")
    print("  - 12-15s : BOUCHE OUVERTE en O (surprise)")
    print()

    t0 = time.time()
    samples = {"neutre":[], "sourire":[], "triste":[], "douleur":[], "bouche_O":[]}
    labels = ["neutre", "sourire", "triste", "douleur", "bouche_O"]

    while time.time() - t0 < 15:
        elapsed = time.time() - t0
        label_idx = min(int(elapsed / 3), 4)
        label = labels[label_idx]

        ret, frame = cap.read()
        if not ret:
            continue

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = fm.process(rgb)
        if res.multi_face_landmarks:
            lm = res.multi_face_landmarks[0].landmark
            mar = _compute_mar(lm)
            smile = _compute_smile_score(lm)
            ear = _compute_ear(lm)
            bs = _compute_brow_squeeze(lm)
            bd = _compute_brow_drop(lm)
            samples[label].append((mar, smile, ear, bs, bd))

    cap.release()

    print("\n=== STATS PAR EMOTION (apres normalisation v2) ===\n")
    for label in labels:
        if not samples[label]:
            print(f"{label:10s} : 0 echantillons")
            continue
        arr = np.array(samples[label])
        n = len(arr)
        print(f"{label:10s} ({n:3d} frames):")
        print(f"  MAR          min={arr[:,0].min():.3f}  med={np.median(arr[:,0]):.3f}  max={arr[:,0].max():.3f}")
        print(f"  smile (norm) min={arr[:,1].min():.4f}  med={np.median(arr[:,1]):.4f}  max={arr[:,1].max():.4f}")
        print(f"  ear          min={arr[:,2].min():.3f}  med={np.median(arr[:,2]):.3f}  max={arr[:,2].max():.3f}")
        print(f"  brow_squeeze min={arr[:,3].min():.4f}  med={np.median(arr[:,3]):.4f}  max={arr[:,3].max():.4f}")
        print(f"  brow_drop    min={arr[:,4].min():.4f}  med={np.median(arr[:,4]):.4f}  max={arr[:,4].max():.4f}")
        print()

    print("=== SEUILS CALIBRES ATTENDUS ===")
    print(f"SMILE_HAPPY_THRESHOLD     = {config.SMILE_HAPPY_THRESHOLD}")
    print(f"SMILE_SAD_THRESHOLD       = {config.SMILE_SAD_THRESHOLD}")
    print(f"MAR_OPEN_MAX              = {config.MAR_OPEN_MAX}")
    print(f"EAR_PAIN_THRESHOLD        = {config.EAR_PAIN_THRESHOLD}")
    print(f"BROW_SQUEEZE_PAIN_THRESHOLD = {config.BROW_SQUEEZE_PAIN_THRESHOLD}")
    print(f"BROW_DROP_SAD_THRESHOLD   = {config.BROW_DROP_SAD_THRESHOLD}")
    print()
    print("Si tes vraies medianes sont TRES differentes des seuils,")
    print("on ajuste les seuils dans config.py et on relance.")


if __name__ == "__main__":
    main()
