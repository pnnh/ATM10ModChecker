"""支持 ``python -m modchecker`` 启动。"""

from __future__ import annotations

import sys

from modchecker.ui.main_window import run_app

if __name__ == "__main__":
    raise SystemExit(run_app(sys.argv))
