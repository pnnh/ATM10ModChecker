"""后台更新线程：逐个下载并替换模组。"""

from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from modchecker.net import Cancelled, HttpClient
from modchecker.updater import ModUpdater, UpdateOutcome


class UpdateWorker(QThread):
    item_done = Signal(object)      # UpdateOutcome，每完成一个就通知界面
    log = Signal(str)
    finished_all = Signal(object)   # list[UpdateOutcome]

    def __init__(self, results, parent=None) -> None:
        super().__init__(parent)
        self._results = list(results)
        self._cancel = threading.Event()
        # 下载不走 JSON API 的限速；单独低速，避免同时打开太多连接
        self._http = HttpClient(timeout=90.0, retries=2, rate_per_sec=2.0,
                                cancel_event=self._cancel)

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:  # noqa: D401 - QThread 入口
        updater = ModUpdater(self._http, log=lambda message: self.log.emit(message))
        outcomes: list[UpdateOutcome] = []
        try:
            for result in self._results:
                if self._cancel.is_set():
                    break
                try:
                    outcome = updater.update(result)
                except Cancelled:
                    break
                except Exception as exc:  # 单个失败不影响其余模组
                    outcome = UpdateOutcome(result, False, f"意外错误：{exc}")
                outcomes.append(outcome)
                self.item_done.emit(outcome)
        finally:
            self.finished_all.emit(outcomes)
