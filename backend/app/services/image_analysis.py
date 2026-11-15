"""Room photo assistance with OpenCV.

What it does: image-quality checks (exposure, contrast, blur), edge map, and dominant straight-line
detection to help the user trace walls. What it does NOT do: measure the room, reconstruct 3D, or detect
objects. Object detection is reported as NOT_ENABLED unless a model is configured — no detections are faked.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def analyze(path: Path, edges_out: Path, detector_path: str = "") -> dict:
    img = cv2.imread(str(path))
    if img is None:
        raise ValueError("Image could not be decoded")
    h, w = img.shape[:2]
    scale = 900 / max(h, w) if max(h, w) > 900 else 1.0
    small = cv2.resize(img, (int(w * scale), int(h * scale))) if scale != 1 else img
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    contrast = float(gray.std())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    edge_density = float((edges > 0).mean())
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80, minLineLength=int(0.15 * max(gray.shape)), maxLineGap=10)
    horiz = vert = diag = 0
    overlay = cv2.cvtColor((edges * 0.35).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    if lines is not None:
        for x1, y1, x2, y2 in lines[:, 0]:
            ang = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1))) % 180
            if ang < 15 or ang > 165:
                horiz += 1
                color = (80, 200, 120)
            elif 75 < ang < 105:
                vert += 1
                color = (230, 180, 60)
            else:
                diag += 1
                color = (90, 140, 240)
            cv2.line(overlay, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
    cv2.imwrite(str(edges_out), overlay)

    checks = []
    if brightness < 60:
        checks.append({"level": "warning", "message": "Photo is dark; turn on room lights for clearer context."})
    elif brightness > 215:
        checks.append({"level": "warning", "message": "Photo is over-exposed."})
    if sharpness < 60:
        checks.append({"level": "warning", "message": "Photo looks blurry; hold the camera steady."})
    if contrast < 25:
        checks.append({"level": "info", "message": "Low contrast; edges and walls may be hard to see."})
    if not checks:
        checks.append({"level": "ok", "message": "Exposure and sharpness look adequate for visual reference."})

    detector = {"status": "NOT_ENABLED",
                "reason": "No object-detection model is configured (OBJECT_DETECTOR_MODEL_PATH). Mark obstacles manually on the plan."}
    if detector_path and Path(detector_path).exists():
        detector = {"status": "CONFIGURED_NOT_RUN", "reason": "A model file is present but no detector adapter is implemented yet."}

    return {
        "width_px": w, "height_px": h,
        "brightness": round(brightness, 1), "contrast": round(contrast, 1), "sharpness": round(sharpness, 1),
        "edge_density": round(edge_density, 4),
        "lines": {"horizontal": horiz, "vertical": vert, "diagonal": diag},
        "quality_checks": checks,
        "object_detection": detector,
        "limitations": [
            "A single photo cannot provide exact dimensions, depth or hidden objects; the room size you entered sets scale.",
            "Detected lines are visual hints for tracing walls and edges, not measurements.",
        ],
        "method": "OpenCV: grayscale statistics, Laplacian variance (sharpness), Canny edges, probabilistic Hough lines.",
    }
