"""后台检测线程。"""

from __future__ import annotations

import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from modchecker.checker import CheckOptions, Checker
from modchecker.logging_setup import get_logger
from modchecker.net import Cancelled

log = get_logger("worker")


class CheckWorker(QThread):
    progress = Signal(str, int)      # 阶段描述, 百分比
    stage = Signal(str, int, int)    # 阶段描述, 已完成, 总数
    log = Signal(str)
    result_ready = Signal(object)    # 单个 ModResult，边查边显示
    finished_ok = Signal(object)     # Report
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, directory: Path, options: CheckOptions, parent=None) -> None:
        super().__init__(parent)
        self._directory = directory
        self._options = options
        self._cancel_evt = threading.Event()
        self._checker: Checker | None = None

    def cancel(self) -> None:
        self._cancel_evt.set()

    def run(self) -> None:  # noqa: D401 - QThread 入口
        try:
            self._checker = Checker(
                self._options,
                log=lambda message: self.log.emit(message),
                progress=lambda label, percent: self.progress.emit(label, percent),
                stage=lambda label, done, total: self.stage.emit(label, done, total),
                cancel=self._cancel_evt,
                on_result=lambda result: self.result_ready.emit(result),
            )
            report = self._checker.run(self._directory)
        except Cancelled:
            log.info("检测已取消")
            self.cancelled.emit()
        except Exception as exc:  # 意外错误带上堆栈，便于排查
            log.exception("检测线程异常退出")
            self.log.emit(traceback.format_exc(limit=4))
            self.failed.emit(str(exc))
        else:
            self.finished_ok.emit(report)
