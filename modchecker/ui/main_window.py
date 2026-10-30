"""主窗口。"""

from __future__ import annotations

import base64
import csv
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QRect, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QFileDialog, QHeaderView, QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QStyle, QStyleOptionButton, QTableView, QVBoxLayout,
                               QHBoxLayout, QWidget)

from modchecker import APP_NAME, __version__, packmeta, scanner
from modchecker.appconfig import Settings, load_settings, save_settings
from modchecker.checker import CheckOptions
from modchecker.i18n import configure as configure_language
from modchecker.i18n import t
from modchecker.logging_setup import get_logger, install_qt_message_handler, setup_logging
from modchecker.models import (ChangeLevel, InstallInfo, ModResult, Origin, Report,
                               UpdateState)
from modchecker.ui.models import COLUMNS, ModFilterProxy, ModTableModel, version_link
from modchecker.ui.settings_dialog import SettingsDialog, pack_source_or_none
from modchecker.ui.update_worker import UpdateWorker
from modchecker.ui.worker import CheckWorker
from modchecker.updater import UpdateOutcome, apply_outcome

log = get_logger("ui")

_STATE_COLUMN = next(i for i, column in enumerate(COLUMNS) if column.key == "state")

# 状态下拉框：文案 key -> 过滤用的状态集合
_STATE_FILTERS: tuple[tuple[str, set[UpdateState] | None], ...] = (
    ("filter.state.all", None),
    ("filter.state.outdated", {UpdateState.OUTDATED}),
    ("filter.state.current", {UpdateState.CURRENT}),
    ("filter.state.unknown", {UpdateState.UNKNOWN}),
    ("filter.state.error", {UpdateState.ERROR}),
)
_ORIGIN_FILTERS: tuple[tuple[str, set[Origin] | None], ...] = (
    ("filter.origin.all", None),
    ("filter.origin.manual", {Origin.MANUAL}),
    ("filter.origin.pack", {Origin.PACK}),
    ("filter.origin.unknown", {Origin.UNKNOWN}),
)

_STYLESHEET = """
QMainWindow, QWidget { background: #f6f7f9; color: #1f2328; }
QGroupBox { border: 1px solid #dcdfe4; border-radius: 6px; margin-top: 8px; padding: 10px; }
QLabel#Title { font-size: 20px; font-weight: 600; }
QLabel#Subtitle { color: #666e79; }
QLabel#InfoChip { background: #ffffff; border: 1px solid #dcdfe4; border-radius: 11px;
                  padding: 3px 10px; color: #40464e; }
QLabel#PackBanner { border-radius: 6px; padding: 8px 12px; font-weight: 600; }
QLineEdit { background: #ffffff; border: 1px solid #d0d4da; border-radius: 5px; padding: 5px 8px; }
QPushButton { background: #ffffff; border: 1px solid #d0d4da; border-radius: 5px; padding: 5px 14px; }
QPushButton:hover { border-color: #4c8dff; color: #1c62e0; }
QPushButton:disabled { background: #f1f2f4; border-color: #dcdfe4; color: #9aa4b1; }
QPushButton#Primary { background: #1c62e0; border-color: #1c62e0; color: #ffffff; font-weight: 600; }
QPushButton#Primary:hover { background: #1550bd; }
QPushButton#Primary:disabled { background: #a9bde5; border-color: #a9bde5; }
QTableView { background: #ffffff; border: 1px solid #dcdfe4; border-radius: 6px;
             gridline-color: #eef0f3; selection-background-color: #e8f0ff;
             selection-color: #1f2328; alternate-background-color: #fbfcfd; }
QHeaderView::section { background: #f1f3f6; border: none; border-right: 1px solid #e6e8ec;
                       padding: 6px; font-weight: 600; }
QProgressBar { border: 1px solid #dcdfe4; border-radius: 5px; background: #ffffff;
               text-align: center; height: 18px; }
QProgressBar::chunk { background: #1c62e0; border-radius: 4px; }
QPlainTextEdit { background: #1f2328; color: #d7dde5; border-radius: 6px;
                 font-family: Consolas, monospace; font-size: 12px; }
"""


class CheckableHeaderView(QHeaderView):
    """表头第 0 列画一个复选框：点击即全选 / 全不选所有可更新模组。"""

    toggled = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._check_state = Qt.CheckState.Unchecked
        self.setSectionsClickable(True)
        self.setHighlightSections(False)

    def check_state(self) -> Qt.CheckState:
        return self._check_state

    def set_check_state(self, state: Qt.CheckState) -> None:
        if state == self._check_state:
            return
        self._check_state = state
        self.updateSection(0)

    def paintSection(self, painter, rect: QRect, logical_index: int) -> None:  # noqa: N802
        super().paintSection(painter, rect, logical_index)
        if logical_index != 0:
            return
        option = QStyleOptionButton()
        size = self.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, self)
        option.rect = QRect(rect.center().x() - size // 2, rect.center().y() - size // 2,
                            size, size)
        option.state = QStyle.StateFlag.State_Enabled
        if self._check_state == Qt.CheckState.Checked:
            option.state |= QStyle.StateFlag.State_On
        elif self._check_state == Qt.CheckState.PartiallyChecked:
            option.state |= QStyle.StateFlag.State_NoChange
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorCheckBox,
                                   option, painter, self)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.logicalIndexAt(event.position().toPoint()) == 0:
            self.toggled.emit(self._check_state != Qt.CheckState.Checked)
            return
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, initial_dir: str = "") -> None:
        super().__init__()
        self.settings: Settings = load_settings()
        self.report: Report | None = None
        self.install: InstallInfo | None = None
        self.worker: CheckWorker | None = None
        self.update_worker: UpdateWorker | None = None
        self._streamed = 0
        self._update_total = 0
        self._update_done = 0
        self._update_ok = 0

        self._build_ui()
        self._retranslate()
        self._restore_state(initial_dir)

    # ------------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)

        header = QVBoxLayout()
        self.title_label = QLabel(APP_NAME)
        self.title_label.setObjectName("Title")
        self.subtitle_label = QLabel()
        self.subtitle_label.setObjectName("Subtitle")
        self.subtitle_label.setWordWrap(True)
        header.addWidget(self.title_label)
        header.addWidget(self.subtitle_label)
        layout.addLayout(header)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.editingFinished.connect(
            lambda: self._inspect_directory(self.path_edit.text().strip()))
        self.browse_btn = QPushButton()
        self.browse_btn.clicked.connect(self._pick_directory)
        self.check_btn = QPushButton()
        self.check_btn.setObjectName("Primary")
        self.check_btn.clicked.connect(self._start_check)
        self.cancel_btn = QPushButton()
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_check)
        self.settings_btn = QPushButton()
        self.settings_btn.clicked.connect(self._open_settings)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.browse_btn)
        path_row.addWidget(self.check_btn)
        path_row.addWidget(self.cancel_btn)
        path_row.addWidget(self.settings_btn)
        layout.addLayout(path_row)

        # 可选的整合包原包：自动探测可能命中同名但版本不同的 zip，显式指定才可靠
        pack_row = QHBoxLayout()
        self.pack_label = QLabel()
        self.pack_edit = QLineEdit()
        self.pack_edit.editingFinished.connect(self._on_pack_source_changed)
        self.pack_zip_btn = QPushButton()
        self.pack_zip_btn.clicked.connect(self._pick_pack_zip)
        self.pack_dir_btn = QPushButton()
        self.pack_dir_btn.clicked.connect(self._pick_pack_dir)
        self.pack_clear_btn = QPushButton()
        self.pack_clear_btn.clicked.connect(self._clear_pack_source)
        pack_row.addWidget(self.pack_label)
        pack_row.addWidget(self.pack_edit, 1)
        pack_row.addWidget(self.pack_zip_btn)
        pack_row.addWidget(self.pack_dir_btn)
        pack_row.addWidget(self.pack_clear_btn)
        layout.addLayout(pack_row)

        info_row = QHBoxLayout()
        info_row.setSpacing(8)
        self.chip_kind = self._chip()
        self.chip_version = self._chip()
        self.chip_loader = self._chip()
        self.chip_pack = self._chip()
        self.chip_index = self._chip()
        for chip in (self.chip_kind, self.chip_version, self.chip_loader,
                     self.chip_pack, self.chip_index):
            info_row.addWidget(chip)
        info_row.addStretch(1)
        layout.addLayout(info_row)

        self.pack_banner = QLabel()
        self.pack_banner.setObjectName("PackBanner")
        self.pack_banner.setStyleSheet("background:#eef1f5;color:#40464e;")
        layout.addWidget(self.pack_banner)

        filter_row = QHBoxLayout()
        self.update_btn = QPushButton()
        self.update_btn.setEnabled(False)
        self.update_btn.clicked.connect(self._batch_update)
        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda *_: self._apply_filters())
        self.state_combo = QComboBox()
        for key, _states in _STATE_FILTERS:
            self.state_combo.addItem("", _states)
        self.state_combo.currentIndexChanged.connect(lambda *_: self._apply_filters())
        self.origin_combo = QComboBox()
        for key, _origins in _ORIGIN_FILTERS:
            self.origin_combo.addItem("", _origins)
        self.origin_combo.currentIndexChanged.connect(lambda *_: self._apply_filters())
        self.only_updates = QCheckBox()
        self.only_updates.stateChanged.connect(lambda *_: self._apply_filters())
        self.export_btn = QPushButton()
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export_csv)
        self.log_btn = QPushButton()
        self.log_btn.setCheckable(True)
        self.log_btn.toggled.connect(self._toggle_log)

        filter_row.addWidget(self.update_btn)
        filter_row.addWidget(self.search_edit, 1)
        filter_row.addWidget(self.state_combo)
        filter_row.addWidget(self.origin_combo)
        filter_row.addWidget(self.only_updates)
        filter_row.addWidget(self.export_btn)
        filter_row.addWidget(self.log_btn)
        layout.addLayout(filter_row)

        self.stats_label = QLabel()
        layout.addWidget(self.stats_label)

        self.model = ModTableModel(self)
        self.model.checks_changed.connect(self._refresh_update_button)
        self.proxy = ModFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.verticalHeader().setVisible(False)
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.viewport().installEventFilter(self)
        self.table.doubleClicked.connect(self._open_project)
        self.table.clicked.connect(self._on_cell_clicked)
        # 列宽固定、不拉伸最后一列，表格超出窗口时用横向滚动条
        self.header_view = CheckableHeaderView(self.table)
        self.header_view.setStretchLastSection(False)
        self.header_view.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.header_view.toggled.connect(self.model.set_all_updates)
        self.table.setHorizontalHeader(self.header_view)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        for position, column in enumerate(COLUMNS):
            self.table.setColumnWidth(position, column.width)
        self.table.sortByColumn(_STATE_COLUMN, Qt.SortOrder.AscendingOrder)
        layout.addWidget(self.table, 1)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setFixedHeight(120)
        self.log_view.setVisible(False)
        layout.addWidget(self.log_view)

        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label = QLabel()
        self.status_label.setObjectName("Subtitle")
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.status_label)
        layout.addLayout(progress_row)

        self.setCentralWidget(central)
        self.setStyleSheet(_STYLESHEET)

    @staticmethod
    def _chip() -> QLabel:
        label = QLabel()
        label.setObjectName("InfoChip")
        return label

    def _retranslate(self) -> None:
        """按当前语言刷新所有静态文案；语言在设置里切换后立即调用。"""
        self.setWindowTitle(f"{t('app.title')} v{__version__}")
        self.title_label.setText(t("app.title"))
        self.subtitle_label.setText(t("app.subtitle"))

        self.path_edit.setPlaceholderText(t("placeholder.path"))
        self.browse_btn.setText(t("button.browse"))
        self.check_btn.setText(t("button.start"))
        self.cancel_btn.setText(t("button.cancel"))
        self.settings_btn.setText(t("button.settings"))

        self.pack_label.setText(t("label.pack"))
        self.pack_edit.setPlaceholderText(t("placeholder.pack"))
        self.pack_zip_btn.setText(t("button.pick_zip"))
        self.pack_dir_btn.setText(t("button.pick_dir"))
        self.pack_clear_btn.setText(t("button.clear"))

        for chip, key in ((self.chip_kind, "chip.kind"), (self.chip_version, "chip.mc"),
                          (self.chip_loader, "chip.loader"), (self.chip_pack, "chip.pack"),
                          (self.chip_index, "chip.index")):
            chip.setText(t(key))

        self.update_btn.setToolTip(t("tip.batch_update"))
        self.search_edit.setPlaceholderText(t("placeholder.search"))
        for combo, items in ((self.state_combo, _STATE_FILTERS),
                             (self.origin_combo, _ORIGIN_FILTERS)):
            for position, (key, _value) in enumerate(items):
                combo.setItemText(position, t(key))
        self.only_updates.setText(t("filter.only_updates"))
        self.export_btn.setText(t("button.export"))
        self.log_btn.setText(t("button.log"))

        self.stats_label.setText(t("stats.empty"))
        self.status_label.setText(t("status.ready"))
        self.pack_banner.setText(t("banner.idle"))

        # 依赖已检测数据的动态文案
        if self.install is not None:
            self._apply_install_info(self.install)
        if self.report is not None:
            self._update_stats(self.report)
            self._update_pack_banner(self.report)
        self.model.refresh_texts()
        self._refresh_update_button()

    def _toggle_log(self, visible: bool) -> None:
        self.log_view.setVisible(visible)

    def _restore_state(self, initial_dir: str = "") -> None:
        if self.settings.window_geometry:
            try:
                self.restoreGeometry(QByteArray(
                    base64.b64decode(self.settings.window_geometry.encode("ascii"))))
            except (ValueError, TypeError) as exc:
                log.warning("恢复窗口位置失败：%s", exc)
        self.pack_edit.setText(self.settings.pack_source)
        # 命令行传入的目录优先于上次使用的目录
        for candidate in (initial_dir, self.settings.last_directory):
            if candidate and Path(candidate).is_dir():
                self.path_edit.setText(candidate)
                self._inspect_directory(candidate)
                break

    # ------------------------------------------------------------------ 目录
    def _pick_directory(self) -> None:
        start = self.path_edit.text().strip() or self.settings.last_directory
        try:
            directory = QFileDialog.getExistingDirectory(self, t("dialog.file.choose_dir"),
                                                         start)
        except Exception:
            log.exception("打开目录选择框失败")
            return
        if directory:
            self.path_edit.setText(directory)
            self._inspect_directory(directory)

    def _apply_install_info(self, info: InstallInfo) -> None:
        unknown = t("chip.value_unknown")
        self.chip_kind.setText(t("chip.kind_value", value=info.kind_label))
        self.chip_version.setText(t("chip.mc_value", value=info.mc_version or unknown))
        loader = info.loader or unknown
        if info.loader_version:
            loader = f"{loader} {info.loader_version}"
        self.chip_loader.setText(t("chip.loader_value", value=loader))
        self.chip_pack.setText(t("chip.pack_value", value=info.pack_version or unknown))

    def _inspect_directory(self, directory: str) -> None:
        if not directory:
            return
        path = Path(directory)
        if not path.is_dir():
            return
        try:
            info = scanner.detect_install(path)
        except scanner.ScanError as exc:
            log.warning("识别安装目录失败：%s", exc)
            self.status_label.setText(str(exc))
            return
        except Exception as exc:  # 目录权限等
            log.exception("读取目录时出错：%s", path)
            self.status_label.setText(t("status.read_failed", error=exc))
            return
        self.install = info
        self._apply_install_info(info)
        self._refresh_index_chip(info)
        self.status_label.setText(t("status.identified", path=info.mods_dir,
                                    count=info.jar_total))
        self.settings.last_directory = str(path)
        save_settings(self.settings)

    # ------------------------------------------------------------------ 整合包原包
    def _pick_pack_zip(self) -> None:
        start = self.pack_edit.text().strip() or self.path_edit.text().strip()
        try:
            path, _ = QFileDialog.getOpenFileName(self, t("dialog.file.choose_pack_zip"), start,
                                                  t("dialog.file.zip_filter"))
        except Exception:
            log.exception("打开文件选择框失败")
            return
        if path:
            self.pack_edit.setText(path)
            self._on_pack_source_changed()

    def _pick_pack_dir(self) -> None:
        start = self.pack_edit.text().strip() or self.path_edit.text().strip()
        try:
            directory = QFileDialog.getExistingDirectory(self, t("dialog.file.choose_pack_dir"),
                                                         start)
        except Exception:
            log.exception("打开目录选择框失败")
            return
        if directory:
            self.pack_edit.setText(directory)
            self._on_pack_source_changed()

    def _clear_pack_source(self) -> None:
        self.pack_edit.clear()
        self._on_pack_source_changed()

    def _on_pack_source_changed(self) -> None:
        self.settings.pack_source = self.pack_edit.text().strip()
        save_settings(self.settings)
        self._refresh_index_chip()

    def _refresh_index_chip(self, info=None) -> None:
        """检测之前就把已知的官方清单信息填进标签，避免一直是“—”。"""
        text = self.pack_edit.text().strip()
        try:
            if text:
                path = Path(text).expanduser()
                if not (path.is_file() or path.is_dir()):
                    self.chip_index.setText(t("chip.index_bad_path"))
                    self.chip_index.setToolTip(text)
                    return
                meta = packmeta.load_pack_reference(path)
                source = t("chip.index_source_specified", source=meta.source or str(path))
            else:
                if info is None:
                    directory = self.path_edit.text().strip()
                    if not directory or not Path(directory).is_dir():
                        return
                    info = scanner.detect_install(Path(directory))
                meta = packmeta.find_local_metadata(info.game_dir, info.root,
                                                    info.game_dir.parent)
                source = t("chip.index_source_instance",
                           source=meta.source or t("chip.index_source_missing"))
        except Exception as exc:      # 清单可能损坏 / 无权限
            log.warning("读取整合包清单失败：%s", exc)
            self.chip_index.setText(t("chip.index_unusable"))
            self.chip_index.setToolTip(str(exc))
            return

        if meta.filenames or meta.sha1s or meta.project_files:
            self.chip_index.setText(t("chip.index_value",
                                      version=meta.pack_version or t("chip.version_unknown"),
                                      items=len(meta.filenames)))
            self.chip_index.setToolTip(t("chip.index_items_tip", source=source,
                                         projects=len(meta.project_files),
                                         names=len(meta.filenames),
                                         hashes=len(meta.sha1s)))
        else:
            self.chip_index.setText(t("chip.index_missing"))
            self.chip_index.setToolTip(source)

    # ------------------------------------------------------------------ 检测
    def _build_options(self) -> CheckOptions | None:
        directory = self.path_edit.text().strip()
        if not directory or not Path(directory).is_dir():
            QMessageBox.warning(self, t("dialog.need_dir.title"), t("dialog.need_dir.text"))
            return None
        if not self.settings.use_modrinth and not self.settings.use_curseforge:
            QMessageBox.warning(self, t("dialog.no_source.title"), t("dialog.no_source.text"))
            return None
        self.settings.pack_source = self.pack_edit.text().strip()
        return CheckOptions(
            game_version=self.settings.game_version.strip(),
            loader=self.settings.loader.strip(),
            include_disabled=self.settings.include_disabled,
            use_modrinth=self.settings.use_modrinth,
            use_curseforge=self.settings.use_curseforge,
            cf_api_key=self.settings.curseforge_api_key,
            concurrency=max(1, self.settings.concurrency),
            verify_official=self.settings.verify_official,
            pack_source=pack_source_or_none(self.settings),
        )

    def _start_check(self) -> None:
        if self.worker is not None:
            return
        directory = self.path_edit.text().strip()
        options = self._build_options()
        if options is None:
            return
        self.report = None
        self._streamed = 0
        self.model.set_results([])
        # 流式追加期间先不排序，避免行在列表里来回跳动
        self.table.setSortingEnabled(False)
        self.export_btn.setEnabled(False)
        self.log_view.clear()
        self.stats_label.setText(t("status.checking_initial"))
        self.pack_banner.setText(t("status.pack_loading"))
        self.progress.setValue(0)
        self._set_running(True)

        try:
            self.worker = CheckWorker(Path(directory), options)
            self.worker.progress.connect(self._on_progress)
            self.worker.stage.connect(self._on_stage)
            self.worker.log.connect(self._on_log)
            self.worker.result_ready.connect(self._on_result_ready)
            self.worker.finished_ok.connect(self._on_finished)
            self.worker.cancelled.connect(self._on_cancelled)
            self.worker.failed.connect(self._on_failed)
            self.worker.finished.connect(self._on_thread_finished)
            self.worker.start()
        except Exception as exc:      # 线程创建失败等
            log.exception("启动检测线程失败")
            self.worker = None
            self._set_running(False)
            QMessageBox.critical(self, t("dialog.check_failed.title"), str(exc))
            return
        log.info("开始检测：%s", directory)

    def _cancel_check(self) -> None:
        if self.update_worker is not None:
            self.cancel_btn.setEnabled(False)
            self.status_label.setText(t("status.stopping_update"))
            self.update_worker.cancel()
            return
        if self.worker is not None:
            self.cancel_btn.setEnabled(False)
            self.status_label.setText(t("status.cancelling"))
            self.worker.cancel()

    def _set_running(self, running: bool) -> None:
        self.check_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.path_edit.setEnabled(not running)
        self._refresh_update_button()

    def _on_progress(self, label: str, percent: int) -> None:
        self.progress.setValue(percent)
        self.status_label.setText(t("status.progress", label=label, percent=percent))

    def _on_stage(self, label: str, done: int, total: int) -> None:
        if total:
            self.status_label.setText(t("status.stage", label=label, done=done, total=total))
        else:
            self.status_label.setText(t("status.stage_plain", label=label))

    def _on_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)
        log.info("%s", message)       # 同时落到 latest.log

    def _on_result_ready(self, result) -> None:
        """后台每查完一个模组就追加一行，用户不必对着空列表等。"""
        self.model.append_result(result)
        self._streamed += 1
        if self._streamed == 1 or self._streamed % 10 == 0:
            self.stats_label.setText(t("status.checking", count=self._streamed))

    def _on_thread_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        self._set_running(False)

    def _on_finished(self, report: Report) -> None:
        self.report = report
        self.model.set_results(report.mods)
        # 检测完成后按统一规则排序，并恢复表头排序
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(_STATE_COLUMN, Qt.SortOrder.AscendingOrder)
        self.progress.setValue(100)
        self.export_btn.setEnabled(bool(report.mods))
        self._apply_filters()
        self._refresh_update_button()
        self._update_stats(report)
        self._update_pack_banner(report)
        self.status_label.setText(t("status.done", seconds=report.elapsed))
        for warning in report.warnings:
            self.log_view.appendPlainText(t("log.warning", text=warning))
            log.warning("%s", warning)
        if report.query_errors:
            self.log_view.appendPlainText(t("log.query_failed_hint", count=report.query_errors))
        log.info("检测完成：%d 个模组，用时 %.1f 秒", report.total, report.elapsed)

    def _on_cancelled(self) -> None:
        self.table.setSortingEnabled(True)
        self.status_label.setText(t("status.cancelled"))
        self.progress.setValue(0)
        self._refresh_update_button()
        log.info("检测被取消（已显示 %d 个模组）", self._streamed)
        if self.report is None:
            if self._streamed:
                self.stats_label.setText(t("status.cancelled_partial", count=self._streamed))
            else:
                self.stats_label.setText(t("stats.empty"))

    def _on_failed(self, message: str) -> None:
        self.table.setSortingEnabled(True)
        self.status_label.setText(t("status.failed"))
        self.progress.setValue(0)
        self._refresh_update_button()
        log.error("检测失败：%s", message)
        if self._streamed:
            self.stats_label.setText(t("status.failed_partial", count=self._streamed))
        else:
            self.stats_label.setText(t("stats.empty"))
        QMessageBox.critical(self, t("dialog.check_failed.title"), message)

    # ------------------------------------------------------------------ 更新
    def _refresh_update_button(self) -> None:
        """根据勾选情况刷新批量更新按钮与表头复选框。"""
        candidates = self.model.update_candidates()
        checked = self.model.checked_results()
        busy = self.worker is not None or self.update_worker is not None
        self.update_btn.setEnabled(bool(checked) and not busy)
        self.update_btn.setText(t("button.batch_update_n", n=len(checked)) if checked
                                else t("button.batch_update"))
        if not candidates:
            state = Qt.CheckState.Unchecked
        elif len(checked) >= len(candidates):
            state = Qt.CheckState.Checked
        elif checked:
            state = Qt.CheckState.PartiallyChecked
        else:
            state = Qt.CheckState.Unchecked
        self.header_view.set_check_state(state)

    def _build_confirm_box(self, results: list[ModResult]) -> tuple[QMessageBox, QPushButton]:
        """组装二次确认弹窗；主/次版本更新需要用户勾选知晓后才能确认。"""
        separator = t("common.list_separator")
        names = separator.join(r.title for r in results[:5])
        if len(results) > 5:
            names = t("dialog.update.more", names=names, count=len(results))

        breaking = [r for r in results
                    if r.change_level in (ChangeLevel.MAJOR, ChangeLevel.MINOR)]
        unclear = [r for r in results if r.change_level is ChangeLevel.UNKNOWN]

        details = [t("dialog.update.irreversible"), t("dialog.update.backup")]
        if breaking:
            listed = separator.join(f"{r.title} ({r.state_label})" for r in breaking[:3])
            if len(breaking) > 3:
                listed = t("dialog.update.more", names=listed, count=len(breaking))
            details.insert(0, t("dialog.update.breaking", names=listed))
        if unclear:
            details.append(t("dialog.update.unclear", count=len(unclear)))

        box = QMessageBox(self)
        box.setWindowTitle(t("dialog.update.title"))
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(t("dialog.update.text", names=names))
        box.setInformativeText("\n\n".join(details))
        confirm = box.addButton(t("dialog.update.accept"), QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton(t("dialog.update.cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        if breaking or unclear:
            aware = QCheckBox(t("dialog.update.aware"), box)
            box.setCheckBox(aware)
            confirm.setEnabled(False)
            aware.toggled.connect(confirm.setEnabled)
        return box, confirm

    def _confirm_update(self, results: list[ModResult]) -> bool:
        """二次确认：更新会写入磁盘且不可撤销，必须先手动备份实例。"""
        box, confirm = self._build_confirm_box(results)
        box.exec()
        return box.clickedButton() is confirm

    def _batch_update(self) -> None:
        results = self.model.checked_results()
        if results and self._confirm_update(results):
            self._start_update(results)

    def _on_cell_clicked(self, index) -> None:
        """版本列 = 打开发版页面；状态列 = 更新单个模组（需二次确认）。"""
        column = COLUMNS[index.column()].key
        result = self.model.result_at(self.proxy.mapToSource(index).row())
        if result is None:
            return
        if column in ("installed", "latest"):
            self._open_url(version_link(result, column))
            return
        if column != "state":
            return
        if not result.can_update:
            if result.has_update:
                self.status_label.setText(t("status.no_direct_link", title=result.title))
            return
        if self.update_worker is not None or self.worker is not None:
            return
        if self._confirm_update([result]):
            self._start_update([result])

    def _open_url(self, url: str) -> None:
        """用系统默认浏览器打开链接；失败时提示而不是静默无反应。"""
        if not url:
            return
        try:
            opened = QDesktopServices.openUrl(QUrl(url))
        except Exception:
            log.exception("打开链接失败：%s", url)
            opened = False
        if not opened:
            self.status_label.setText(t("status.open_url_failed", url=url))
            log.warning("无法打开浏览器：%s", url)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """鼠标移到可点击的单元格上时换成手型光标。"""
        if obj is self.table.viewport() and event.type() == QEvent.Type.MouseMove:
            index = self.table.indexAt(event.position().toPoint())
            clickable = False
            if index.isValid():
                column = COLUMNS[index.column()].key
                result = self.model.result_at(self.proxy.mapToSource(index).row())
                if column in ("installed", "latest"):
                    clickable = bool(result is not None and version_link(result, column))
                elif column == "state" and result is not None:
                    clickable = result.can_update
            if clickable:
                self.table.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.table.viewport().unsetCursor()
        return super().eventFilter(obj, event)

    def _start_update(self, results: list[ModResult]) -> None:
        if self.update_worker is not None or self.worker is not None:
            return
        self._update_total = len(results)
        self._update_done = 0
        self._update_ok = 0
        self.progress.setRange(0, self._update_total)
        self.progress.setValue(0)
        self.log_view.appendPlainText(t("log.update_start", count=self._update_total))
        try:
            self.update_worker = UpdateWorker(results, self)
            self.update_worker.item_done.connect(self._on_update_done)
            self.update_worker.log.connect(self._on_log)
            self.update_worker.finished_all.connect(self._on_update_finished)
            self.update_worker.finished.connect(self._on_update_thread_finished)
            self.update_worker.start()
        except Exception as exc:
            log.exception("启动更新线程失败")
            self.update_worker = None
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            QMessageBox.critical(self, t("dialog.error.title"),
                                 t("dialog.error.text", error=exc))
            return
        self.check_btn.setEnabled(False)
        self.path_edit.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.update_btn.setEnabled(False)
        self.status_label.setText(t("status.updating", done=1, total=self._update_total))
        log.info("开始更新 %d 个模组", self._update_total)

    def _on_update_done(self, outcome: UpdateOutcome) -> None:
        apply_outcome(outcome.result, outcome)
        self.model.update_result(outcome.result)
        self._update_done += 1
        if outcome.ok:
            self._update_ok += 1
            self.log_view.appendPlainText(
                t("log.update_ok", title=outcome.result.title, message=outcome.message))
            log.info("更新成功：%s（%s）", outcome.result.title, outcome.message)
        else:
            self.log_view.appendPlainText(
                t("log.update_failed", title=outcome.result.title, message=outcome.message))
            log.error("更新失败：%s（%s）", outcome.result.title, outcome.message)
        self.progress.setValue(self._update_done)
        self.status_label.setText(t("status.updating_progress", done=self._update_done,
                                    total=self._update_total, ok=self._update_ok))

    def _on_update_finished(self, outcomes) -> None:
        self._apply_filters()
        failed = [item for item in outcomes if not item.ok]
        if self.report is not None:
            self._update_stats(self.report)
        message = t("status.update_done", ok=len(outcomes) - len(failed))
        if len(outcomes) < self._update_total:
            message += t("status.update_cancelled_suffix", total=self._update_total)
        if failed:
            message += t("status.update_failed_suffix", failed=len(failed))
            separator = t("common.list_separator")
            QMessageBox.warning(self, t("dialog.update_failed.title"),
                                "\n".join(f"{item.result.title}{separator}{item.message}"
                                          for item in failed[:10]))
        self.status_label.setText(message)

    def _on_update_thread_finished(self) -> None:
        if self.update_worker is not None:
            self.update_worker.deleteLater()
            self.update_worker = None
        finished_all = bool(self._update_total) and self._update_done >= self._update_total
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if finished_all else 0)
        self.check_btn.setEnabled(True)
        self.path_edit.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._update_total = 0
        self._refresh_update_button()

    # ------------------------------------------------------------------ 展示
    def _update_pack_banner(self, report: Report) -> None:
        pack = report.pack
        if pack.latest is None:
            self.pack_banner.setText(pack.message or t("banner.pack_unknown_generic"))
            self.pack_banner.setStyleSheet("background:#f1f3f5;color:#666e79;")
            return
        if pack.update_available:
            self.pack_banner.setText(t("banner.pack_update", message=pack.message,
                                       date=pack.latest.uploaded_at[:10],
                                       count=pack.release_count))
            self.pack_banner.setStyleSheet("background:#fff4e0;color:#a35b00;")
        else:
            self.pack_banner.setText(t("banner.pack_current", message=pack.message))
            self.pack_banner.setStyleSheet("background:#e7f7ec;color:#1c7a3e;")

        index = report.index
        if index and index.usable:
            self.chip_index.setText(t("chip.index_value",
                                      version=index.pack_version or t("chip.version_unknown"),
                                      items=len(index.filenames)))
            self.chip_index.setToolTip(t("chip.index_source_tip", source=index.source))
        else:
            self.chip_index.setText(t("chip.index_unusable"))
            self.chip_index.setToolTip(t("chip.index_no_classify"))

        install = report.install
        self.install = install
        self._apply_install_info(install)

    def _update_stats(self, report: Report) -> None:
        manual = report.count_origin(Origin.MANUAL)
        pack = report.count_origin(Origin.PACK)
        unknown_origin = report.count_origin(Origin.UNKNOWN)
        failed = report.count_state(UpdateState.ERROR)
        unknown = report.unknown - failed
        self.stats_label.setText(
            f"{t('stats.total', n=report.total)}　"
            f"<span style='color:#d98e04;font-weight:600'>"
            f"{t('stats.outdated', n=report.outdated)}</span>　"
            f"<span style='color:#2f9e44;'>{t('stats.current', n=report.current)}</span>　"
            f"<span style='color:#8a8a8a;'>{t('stats.unknown', n=unknown)}</span>　"
            f"<span style='color:#c92a2a;'>{t('stats.failed', n=failed)}</span>　|　"
            f"<span style='color:#1c7ed6;font-weight:600'>"
            f"{t('stats.manual', n=manual)}</span>　"
            f"{t('stats.pack', n=pack)}　{t('stats.origin_unknown', n=unknown_origin)}"
        )

    def _apply_filters(self) -> None:
        self.proxy.set_text(self.search_edit.text())
        states = self.state_combo.currentData()
        self.proxy.set_states(states or set())
        origins = self.origin_combo.currentData()
        self.proxy.set_origins(origins or set())
        self.proxy.set_only_updates(self.only_updates.isChecked())

    def _open_project(self, index) -> None:
        if COLUMNS[index.column()].key in ("select", "state", "installed", "latest"):
            return                      # 这些列单击已有各自的行为
        source_row = self.proxy.mapToSource(index).row()
        result = self.model.result_at(source_row)
        if result is not None and result.project_url:
            self._open_url(result.project_url)

    # ------------------------------------------------------------------ 导出
    def _export_csv(self) -> None:
        if self.report is None:
            return
        default = f"atm10-modcheck-{datetime.now():%Y%m%d-%H%M}.csv"
        try:
            path, _ = QFileDialog.getSaveFileName(self, t("dialog.file.export"), default,
                                                  t("dialog.file.csv_filter"))
        except Exception:
            log.exception("打开保存对话框失败")
            return
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([t("csv.status"), t("csv.mod"), t("csv.origin"),
                                 t("csv.installed"), t("csv.installed_date"),
                                 t("csv.latest"), t("csv.latest_date"), t("csv.source"),
                                 t("csv.filename"), t("csv.mod_id"), t("csv.link"),
                                 t("csv.note")])
                for result in self.report.mods:
                    writer.writerow([
                        result.state_label, result.title, result.origin_label,
                        result.installed_version, _csv_date(result.installed_date),
                        result.latest_version, _csv_date(result.latest_date),
                        result.source_label, result.jar.filename, result.jar.mod_id,
                        result.project_url, result.note,
                    ])
        except OSError as exc:
            log.error("导出 CSV 失败：%s", exc)
            QMessageBox.critical(self, t("dialog.export_failed.title"), str(exc))
            return
        except Exception as exc:      # 数据异常也不该让界面崩掉
            log.exception("导出 CSV 时出错")
            QMessageBox.critical(self, t("dialog.export_failed.title"),
                                 t("dialog.error.text", error=exc))
            return
        self.status_label.setText(t("status.exported", path=path))
        log.info("已导出：%s", path)

    # ------------------------------------------------------------------ 其它
    def _open_settings(self) -> None:
        try:
            dialog = SettingsDialog(self.settings, self)
            accepted = dialog.exec()
        except Exception as exc:
            log.exception("打开设置窗口失败")
            QMessageBox.critical(self, t("dialog.error.title"),
                                 t("dialog.error.text", error=exc))
            return
        if not accepted:
            return
        previous_language = self.settings.language
        dialog.apply_to(self.settings)
        save_settings(self.settings)
        self.pack_edit.setText(self.settings.pack_source)
        if self.settings.language != previous_language:
            language = configure_language(self.settings.language)
            log.info("界面语言切换为：%s", language)
            self._retranslate()
        if self.settings.last_directory:
            self._inspect_directory(self.settings.last_directory)
        else:
            self._refresh_index_chip()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.update_worker is not None:
            self.update_worker.cancel()
            if not self.update_worker.wait(5000):
                log.warning("更新线程 5 秒内没有退出，仍将关闭窗口")
        if self.worker is not None:
            self.worker.cancel()
            if not self.worker.wait(3000):
                log.warning("检测线程 3 秒内没有退出，仍将关闭窗口")
        try:
            self.settings.pack_source = self.pack_edit.text().strip()
            geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self.settings.window_geometry = geometry
            save_settings(self.settings)
        except (OSError, ValueError) as exc:
            log.warning("保存窗口状态失败：%s", exc)
        super().closeEvent(event)


def _csv_date(value) -> str:
    try:
        return value.astimezone().strftime("%Y-%m-%d") if value else ""
    except (AttributeError, ValueError, OSError):
        return ""


def run_app(argv: list[str]) -> int:
    log_dir = setup_logging()
    install_qt_message_handler()
    settings = load_settings()
    language = configure_language(settings.language)
    log.info("日志目录：%s", log_dir)
    log.info("界面语言：%s（设置：%s）", language, settings.language or "auto")

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    if sys.platform == "win32":       # macOS / Linux 使用系统默认字体，避免缺字回退
        app.setFont(QFont("Microsoft YaHei UI", 9))
    try:
        window = MainWindow(argv[1] if len(argv) > 1 else "")
        window.show()
    except Exception:
        log.exception("创建主窗口失败")
        QMessageBox.critical(None, t("dialog.error.title"), t("dialog.error_text_crash"))
        return 1
    return app.exec()
