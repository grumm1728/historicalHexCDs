#!/usr/bin/env python3
"""Build timeline data and stage web assets for static hosting."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web"
PROCESSED_ROOT = ROOT / "data_processed"


def run_build_timeline() -> None:
    cmd = [sys.executable, str(ROOT / "scripts" / "build_all_historical.py"), "--allow-modern-outline-fallback"]
    subprocess.run(cmd, check=True, cwd=str(ROOT))


def stage_data_for_web() -> None:
    target = WEB_ROOT / "data_processed"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(PROCESSED_ROOT, target)


def main() -> None:
    run_build_timeline()
    stage_data_for_web()
    print("Staged web assets at", WEB_ROOT)


if __name__ == "__main__":
    main()
