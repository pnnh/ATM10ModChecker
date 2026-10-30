"""运行日志：同时写入标准输出与 ``.ATM10ModChecker/logs/latest.log``，并按天切片。

约定：
* 日志目录取**程序所在目录**下 ``.ATM10ModChecker/logs``（打包后即 exe 旁边）：设置、缓存
  与日志全部收在同一个文件夹里，用户删掉它就算卸载干净；该目录不可写时退回用户目录；
* 最新的日志永远叫 ``latest.log``，跨天后旧内容改名为 ``ATM10ModChecker-YYYY-MM-DD.log``；
* 只记录 INFO 及以上级别（INFO / WARNING / ERROR / CRITICAL）；
* 从控制台启动时同时输出到标准输出；打包成窗口程序（无控制台）时自动附着到
  调用方控制台，保证 ``ATM10ModChecker.exe`` 在终端里运行时仍能看到日志。
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from datetime import date
from pathlib import Path

from modchecker import APP_ID

LOGGER_NAME = "ATM10ModChecker"
DATA_DIR_NAME = ".ATM10ModChecker"
LATEST_NAME = "latest.log"
LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
KEEP_DAYS = 30

_configured = False
_initial_lock = threading.Lock()


# ---------------------------------------------------------------------- 目录
def program_dir() -> Path:
    """程序所在目录：打包后是 exe 所在目录，源码运行时是仓库根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _user_data_dir() -> Path:
    """程序目录不可写时的退路：用户目录下的应用数据（按平台约定选位置）。"""
    if sys.platform == "win32":
        root = os.environ.get("APPDATA")
        base = Path(root) if root else Path.home() / "AppData" / "Roaming"
        return base / APP_ID
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_ID
    root = os.environ.get("XDG_STATE_HOME")
    base = Path(root) if root else Path.home() / ".local" / "state"
    return base / APP_ID


def _writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


_data_dir: Path | None = None


def data_dir() -> Path:
    """全部运行时数据（设置 / 缓存 / 日志）的根目录。

    优先放在**程序所在目录**的 ``.ATM10ModChecker`` 下 —— 源码运行时是仓库根目录，
    打包后是 exe 所在目录，所以用户卸载时只需删掉这个文件夹；
    该位置不可写（例如装在 ``C:\\Program Files``、macOS 的只读卷）时退回用户目录。
    """
    global _data_dir
    if _data_dir is not None:
        return _data_dir
    for candidate in (program_dir() / DATA_DIR_NAME, _user_data_dir()):
        if _writable(candidate):
            _data_dir = candidate
            return _data_dir
    _data_dir = _user_data_dir()
    return _data_dir


def log_directory() -> Path:
    """日志目录（``<data_dir>/logs``），并确保它存在。"""
    directory = data_dir() / "logs"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:      # 极端情况下交给 DailyFileHandler 自己兜底
        pass
    return directory


# ---------------------------------------------------------------------- 处理器
class DailyFileHandler(logging.FileHandler):
    """始终写 ``latest.log``；跨天时把已有内容改名成带日期的文件。"""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._date = date.today()
        super().__init__(directory / LATEST_NAME, mode="a", encoding="utf-8", delay=False)
        self._prune()

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102 - logging 接口
        try:
            today = date.fromtimestamp(record.created)
        except (OverflowError, OSError, ValueError):
            today = self._date
        if today != self._date:
            self._rotate(today)
        super().emit(record)

    def _rotate(self, today: date) -> None:
        """把当前 latest.log 归档为 old date 的文件，再开一个新的 latest.log。"""
        self.acquire()
        try:
            if self.stream is not None:
                self.stream.close()
                self.stream = None
            source = Path(self.baseFilename)
            target = self.directory / f"{APP_ID}-{self._date:%Y-%m-%d}.log"
            try:
                if source.exists() and source.stat().st_size:
                    if target.exists():
                        target.unlink()
                    source.rename(target)
            except OSError:
                pass
            self._date = today
            self.stream = self._open()
        finally:
            self.release()

    def _prune(self) -> None:
        """只保留最近 ``KEEP_DAYS`` 天的归档，避免无限增长。"""
        try:
            archives = sorted(self.directory.glob(f"{APP_ID}-*.log"), reverse=True)
        except OSError:
            return
        for stale in archives[KEEP_DAYS:]:
            try:
                stale.unlink()
            except OSError:
                pass


def _attach_console() -> bool:
    """打包为窗口程序时没有控制台；从终端运行时附着到父进程控制台。"""
    if sys.stdout is not None and sys.stderr is not None:
        return True
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        ATTACH_PARENT_PROCESS = -1
        if not ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            return False
        stream = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        sys.stdout = stream
        sys.stderr = stream
        return True
    except Exception:  # 附着失败不影响 GUI 运行
        return False


def _console_handler() -> logging.Handler | None:
    if not _attach_console() or sys.stdout is None:
        return None
    try:
        # 控制台编码（例如 Windows 的 cp936）无法表示的字符用 ? 代替，
        # 避免日志本身把程序弄崩。
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="replace")
    except (OSError, ValueError):
        pass
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    return handler


# ---------------------------------------------------------------------- 初始化
def get_logger(name: str = "") -> logging.Logger:
    """取本程序的 logger；``name`` 为空时返回根 logger。"""
    return logging.getLogger(LOGGER_NAME if not name else f"{LOGGER_NAME}.{name}")


def setup_logging(level: int = logging.INFO) -> Path:
    """初始化日志系统，返回日志目录。重复调用无副作用。"""
    global _configured
    with _initial_lock:
        directory = log_directory()
        if _configured:
            return directory
        root = logging.getLogger(LOGGER_NAME)
        root.setLevel(level)
        root.propagate = False
        formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
        try:
            file_handler: logging.Handler = DailyFileHandler(directory)
        except OSError:
            file_handler = logging.NullHandler()
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        console = _console_handler()
        if console is not None:
            root.addHandler(console)
        logging.raiseExceptions = False    # 日志写失败不要反过来影响程序
        _configured = True
        install_exception_hooks()
        return directory


def install_exception_hooks() -> None:
    """把未捕获异常（主线程 / 子线程）写进日志。"""
    log = get_logger("crash")

    def handle(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("未捕获的异常", exc_info=(exc_type, exc, tb))

    def handle_thread(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        log.critical("线程 %s 中的未捕获异常", getattr(args.thread, "name", "?"),
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = handle
    threading.excepthook = handle_thread


def install_qt_message_handler() -> None:
    """把 Qt 自身的警告 / 错误也收进日志（Qt 默认直接打印到 stderr）。"""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:  # 没有 Qt 时静默跳过
        return
    log = get_logger("qt")
    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handler(mode, context, message: str) -> None:  # noqa: ANN001 - Qt 回调
        level = levels.get(mode, logging.INFO)
        if level < logging.INFO:   # 只记录 INFO 及以上
            return
        log.log(level, "%s", message)

    qInstallMessageHandler(handler)   # 返回的旧处理器不需要保留
