# SPDX-FileCopyrightText: 2026 pnnh
# SPDX-License-Identifier: AGPL-3.0-or-later
"""目标程序入口：ATM10 模组更新检测器。"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


def _ensure_repo_root() -> None:
    """直接用脚本运行时把仓库根目录放进 ``sys.path``（PyInstaller 打包后无需处理）。"""
    if getattr(sys, "frozen", False):
        return
    root = str(Path(__file__).resolve().parent)
    if root not in sys.path:
        sys.path.insert(0, root)


def main() -> int:
    _ensure_repo_root()

    # 日志要在任何业务代码之前就绪：即使后面导入 Qt 失败，也能留下记录。
    from modchecker.logging_setup import get_logger, setup_logging

    log_dir = setup_logging()
    log = get_logger("main")
    log.info("程序启动：%s", " ".join(sys.argv))

    # 命令行信息（CI 用来验证打包产物能否正常启动）
    from modchecker import APP_NAME, __version__

    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"{APP_NAME} {__version__}")
        return 0
    if "--help" in sys.argv or "-h" in sys.argv:
        print(f"{APP_NAME} {__version__}\n\n"
              "Usage: ATM10ModChecker [MODS_DIRECTORY]\n"
              "       ATM10ModChecker --version\n\n"
              "Without arguments the app opens in GUI mode.\n")
        return 0

    try:
        from modchecker.ui.main_window import run_app
    except ImportError as exc:  # 缺少 Qt 绑定时给出明确指引
        log.exception("导入界面模块失败")
        if "PySide6" in str(exc):
            message = ("缺少依赖 PySide6。请先执行：pip install -r requirements.txt\n"
                       "Missing dependency PySide6. Please run: pip install -r requirements.txt")
            print(message, file=sys.stderr)
            return 2
        raise

    log.info("日志目录：%s", log_dir)
    try:
        return run_app(sys.argv)
    except KeyboardInterrupt:
        log.warning("用户中断")
        return 130
    except Exception:
        log.critical("程序异常退出", exc_info=True)
        # 走到这里说明连界面都没能建立，直接用标准错误兜底
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
