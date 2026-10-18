"""Точка входа для сборки в .exe (PyInstaller) и для автозапуска без установки пакета."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from arc_overlay.app import main  # noqa: E402

sys.exit(main())
