"""Measure Studio import/window construction without loading the TTS engine."""
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    code = r'''
import json, sys, time
t0 = time.perf_counter()
import studio
t1 = time.perf_counter()
from PySide6.QtWidgets import QApplication
t2 = time.perf_counter()
app = QApplication([])
t3 = time.perf_counter()
window = studio.StudioWindow()
t4 = time.perf_counter()
print(json.dumps({
    "import_seconds": round(t1-t0, 3),
    "qt_import_seconds": round(t2-t1, 3),
    "qapplication_seconds": round(t3-t2, 3),
    "window_seconds": round(t4-t3, 3),
    "total_seconds": round(t4-t0, 3),
    "engine_state": window.engine_state,
    "model_load_count": 0 if window.adapter is None else getattr(window.adapter.session, "model_load_count", None),
    "torch_imported": "torch" in sys.modules,
    "omnivoice_imported": "omnivoice" in sys.modules,
}, ensure_ascii=False))
window.close()
'''
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    print(completed.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
