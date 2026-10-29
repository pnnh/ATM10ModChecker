"""目标程序入口：ATM10 模组更新检测器。"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from modchecker.ui.main_window import run_app
    except ImportError as exc:  # 缺少 Qt 绑定时给出明确指引
        if "PySide6" in str(exc):
            print("缺少依赖 PySide6。请先执行：pip install -r requirements.txt", file=sys.stderr)
            return 2
        raise

    return run_app(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
