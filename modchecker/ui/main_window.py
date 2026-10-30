"""主窗口。"""

from __future__ import annotations

import csv
import base64
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QRect, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QStyle, QStyleOptionButton,
                               QTableView, QVBoxLayout, QWidget)

from modchecker import APP_NAME, __version__, packmeta, scanner
from modchecker.appconfig import Settings, load_settings, save_settings
from modchecker.checker import CheckOptions
from modchecker.models import ChangeLevel, ModResult, Origin, Report, UpdateState
from modchecker.ui.models import COLUMNS, ModFilterProxy, ModTableModel, version_link
from modchecker.ui.settings_dialog import SettingsDialog, pack_source_or_none
from modchecker.ui.update_worker import UpdateWorker
from modchecker.ui.worker import CheckWorker
from modchecker.updater import UpdateOutcome, apply_outcome

_STATE_COLUMN = next(i for i, column in enumerate(COLUMNS) if column.key == "state")

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
        self.worker: CheckWorker | None = None
        self.update_worker: UpdateWorker | None = None
        self._streamed = 0
        self._update_total = 0
        self._update_done = 0
        self._update_ok = 0

        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(1320, 840)
        self._build_ui()
        self._restore_state(initial_dir)

    # ------------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)

        header = QVBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("Title")
        subtitle = QLabel("比对 mods 目录中的 jar 与 Modrinth / CurseForge 上的最新版本，"
                          "区分整合包自带与手动添加的模组，并可按需把选定模组更新到最新版本。")
        subtitle.setObjectName("Subtitle")
        subtitle.setWordWrap(True)
        header.addWidget(title)
        header.addWidget(subtitle)
        layout.addLayout(header)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择 ATM10 安装目录（客户端 .minecraft 目录或服务端 ServerFiles 目录）")
        self.path_edit.editingFinished.connect(
            lambda: self._inspect_directory(self.path_edit.text().strip()))
        browse_btn = QPushButton("浏览…")
        browse_btn.clicked.connect(self._pick_directory)
        self.check_btn = QPushButton("开始检测")
        self.check_btn.setObjectName("Primary")
        self.check_btn.clicked.connect(self._start_check)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_check)
        settings_btn = QPushButton("设置")
        settings_btn.clicked.connect(self._open_settings)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse_btn)
        path_row.addWidget(self.check_btn)
        path_row.addWidget(self.cancel_btn)
        path_row.addWidget(settings_btn)
        layout.addLayout(path_row)

        # 可选的整合包原包：自动探测可能命中同名但版本不同的 zip，显式指定才可靠
        pack_row = QHBoxLayout()
        pack_label = QLabel("整合包原包：")
        self.pack_edit = QLineEdit()
        self.pack_edit.setPlaceholderText(
            "可选：整合包原始 zip，或原始 zip 解压后的纯净目录（留空则用实例自带的清单）")
        self.pack_edit.editingFinished.connect(self._on_pack_source_changed)
        pack_zip_btn = QPushButton("选择 zip…")
        pack_zip_btn.clicked.connect(self._pick_pack_zip)
        pack_dir_btn = QPushButton("选择目录…")
        pack_dir_btn.clicked.connect(self._pick_pack_dir)
        pack_clear_btn = QPushButton("清除")
        pack_clear_btn.clicked.connect(self._clear_pack_source)
        pack_row.addWidget(pack_label)
        pack_row.addWidget(self.pack_edit, 1)
        pack_row.addWidget(pack_zip_btn)
        pack_row.addWidget(pack_dir_btn)
        pack_row.addWidget(pack_clear_btn)
        layout.addLayout(pack_row)

        info_row = QHBoxLayout()
        info_row.setSpacing(8)
        self.chip_kind = self._chip("类型：-")
        self.chip_version = self._chip("Minecraft：-")
        self.chip_loader = self._chip("加载器：-")
        self.chip_pack = self._chip("整合包版本：-")
        self.chip_index = self._chip("官方清单：-")
        for chip in (self.chip_kind, self.chip_version, self.chip_loader,
                     self.chip_pack, self.chip_index):
            info_row.addWidget(chip)
        info_row.addStretch(1)
        layout.addLayout(info_row)

        self.pack_banner = QLabel("尚未检测")
        self.pack_banner.setObjectName("PackBanner")
        self.pack_banner.setStyleSheet("background:#eef1f5;color:#40464e;")
        layout.addWidget(self.pack_banner)

        filter_row = QHBoxLayout()
        self.update_btn = QPushButton("批量更新")
        self.update_btn.setEnabled(False)
        self.update_btn.setToolTip("勾选左侧复选框后可用：把所选模组更新到最新版本")
        self.update_btn.clicked.connect(self._batch_update)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索模组名 / 文件名 / modId")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda *_: self._apply_filters())
        self.state_combo = QComboBox()
        self.state_combo.addItem("全部状态", None)
        self.state_combo.addItem("可更新", {UpdateState.OUTDATED})
        self.state_combo.addItem("已最新", {UpdateState.CURRENT})
        self.state_combo.addItem("未知", {UpdateState.UNKNOWN})
        self.state_combo.addItem("查询失败", {UpdateState.ERROR})
        self.state_combo.currentIndexChanged.connect(lambda *_: self._apply_filters())
        self.origin_combo = QComboBox()
        self.origin_combo.addItem("全部归属", None)
        self.origin_combo.addItem("手动添加", {Origin.MANUAL})
        self.origin_combo.addItem("整合包自带", {Origin.PACK})
        self.origin_combo.addItem("未知归属", {Origin.UNKNOWN})
        self.origin_combo.currentIndexChanged.connect(lambda *_: self._apply_filters())
        self.only_updates = QCheckBox("只看可更新")
        self.only_updates.stateChanged.connect(lambda *_: self._apply_filters())
        self.export_btn = QPushButton("导出 CSV")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export_csv)
        self.log_btn = QPushButton("日志")
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

        self.stats_label = QLabel("—")
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
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("Subtitle")
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.status_label)
        layout.addLayout(progress_row)

        self.setCentralWidget(central)
        self.setStyleSheet(_STYLESHEET)

    @staticmethod
    def _chip(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("InfoChip")
        return label

    def _toggle_log(self, visible: bool) -> None:
        self.log_view.setVisible(visible)

    def _restore_state(self, initial_dir: str = "") -> None:
        if self.settings.window_geometry:
            try:
                self.restoreGeometry(QByteArray(
                    base64.b64decode(self.settings.window_geometry.encode("ascii"))))
            except Exception:
                pass
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
        directory = QFileDialog.getExistingDirectory(self, "选择 ATM10 安装目录", start)
        if directory:
            self.path_edit.setText(directory)
            self._inspect_directory(directory)

    def _inspect_directory(self, directory: str) -> None:
        if not directory:
            return
        path = Path(directory)
        if not path.is_dir():
            return
        try:
            info = scanner.detect_install(path)
        except scanner.ScanError as exc:
            self.status_label.setText(str(exc))
            return
        except Exception as exc:  # 目录权限等
            self.status_label.setText(f"读取目录失败：{exc}")
            return
        self.chip_kind.setText(f"类型：{info.kind_label}")
        self.chip_version.setText(f"Minecraft：{info.mc_version or '未识别'}")
        loader = info.loader or "未识别"
        if info.loader_version:
            loader = f"{loader} {info.loader_version}"
        self.chip_loader.setText(f"加载器：{loader}")
        self.chip_pack.setText(f"整合包版本：{info.pack_version or '未识别'}")
        self._refresh_index_chip(info)
        self.status_label.setText(f"已识别 mods 目录：{info.mods_dir}（{info.jar_total} 个 jar）")
        self.settings.last_directory = str(path)
        save_settings(self.settings)

    # ------------------------------------------------------------------ 整合包原包
    def _pick_pack_zip(self) -> None:
        start = self.pack_edit.text().strip() or self.path_edit.text().strip()
        path, _ = QFileDialog.getOpenFileName(self, "选择整合包原始 zip", start,
                                              "Zip 文件 (*.zip)")
        if path:
            self.pack_edit.setText(path)
            self._on_pack_source_changed()

    def _pick_pack_dir(self) -> None:
        start = self.pack_edit.text().strip() or self.path_edit.text().strip()
        directory = QFileDialog.getExistingDirectory(self, "选择整合包解压后的目录", start)
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
        if text:
            path = Path(text).expanduser()
            if not (path.is_file() or path.is_dir()):
                self.chip_index.setText("官方清单：路径无效")
                self.chip_index.setToolTip(text)
                return
            meta = packmeta.load_pack_reference(path)
            source = f"指定来源：{meta.source or path}"
        else:
            if info is None:
                directory = self.path_edit.text().strip()
                if not directory or not Path(directory).is_dir():
                    return
                try:
                    info = scanner.detect_install(Path(directory))
                except Exception:
                    return
            meta = packmeta.find_local_metadata(info.game_dir, info.root, info.game_dir.parent)
            source = f"实例目录：{meta.source or '未找到可用清单'}"

        if meta.filenames or meta.sha1s or meta.project_files:
            version = meta.pack_version or "未知版本"
            self.chip_index.setText(f"官方清单：{version} / {len(meta.filenames)} 项")
            self.chip_index.setToolTip(
                f"{source}\n项目 {len(meta.project_files)} 个，"
                f"文件名 {len(meta.filenames)} 个，哈希 {len(meta.sha1s)} 个")
        else:
            self.chip_index.setText("官方清单：未找到")
            self.chip_index.setToolTip(source)

    # ------------------------------------------------------------------ 检测
    def _build_options(self) -> CheckOptions | None:
        directory = self.path_edit.text().strip()
        if not directory or not Path(directory).is_dir():
            QMessageBox.warning(self, "需要安装目录", "请先选择 ATM10 的安装目录。")
            return None
        if not self.settings.use_modrinth and not self.settings.use_curseforge:
            QMessageBox.warning(self, "没有可用的数据源", "请至少启用一个数据源（Modrinth 或 CurseForge）。")
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
        self.stats_label.setText("检测中…")
        self.pack_banner.setText("正在获取整合包版本信息…")
        self.progress.setValue(0)
        self._set_running(True)

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

    def _cancel_check(self) -> None:
        if self.update_worker is not None:
            self.cancel_btn.setEnabled(False)
            self.status_label.setText("正在停止更新…")
            self.update_worker.cancel()
            return
        if self.worker is not None:
            self.cancel_btn.setEnabled(False)
            self.status_label.setText("正在取消…")
            self.worker.cancel()

    def _set_running(self, running: bool) -> None:
        self.check_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.path_edit.setEnabled(not running)
        self._refresh_update_button()

    def _on_progress(self, label: str, percent: int) -> None:
        self.progress.setValue(percent)
        self.status_label.setText(f"{label}… {percent}%")

    def _on_stage(self, label: str, done: int, total: int) -> None:
        if total:
            self.status_label.setText(f"{label}… {done}/{total}")
        else:
            self.status_label.setText(f"{label}…")

    def _on_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def _on_result_ready(self, result) -> None:
        """后台每查完一个模组就追加一行，用户不必对着空列表等。"""
        self.model.append_result(result)
        self._streamed += 1
        if self._streamed == 1 or self._streamed % 10 == 0:
            self.stats_label.setText(f"检测中… 已显示 {self._streamed} 个模组")

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
        self.status_label.setText(f"检测完成，用时 {report.elapsed:.1f} 秒")
        for warning in report.warnings:
            self.log_view.appendPlainText(f"[警告] {warning}")
        if report.query_errors:
            self.log_view.appendPlainText(f"[提示] {report.query_errors} 个模组查询失败，可稍后重试。")

    def _on_cancelled(self) -> None:
        self.table.setSortingEnabled(True)
        self.status_label.setText("已取消")
        self.progress.setValue(0)
        self._refresh_update_button()
        if self.report is None:
            if self._streamed:
                self.stats_label.setText(f"已取消，已显示 {self._streamed} 个模组（未完成）")
            else:
                self.stats_label.setText("—")

    def _on_failed(self, message: str) -> None:
        self.table.setSortingEnabled(True)
        self.status_label.setText("检测失败")
        self.progress.setValue(0)
        self._refresh_update_button()
        if self._streamed:
            self.stats_label.setText(f"检测失败，已显示 {self._streamed} 个模组（未完成）")
        else:
            self.stats_label.setText("—")
        QMessageBox.critical(self, "检测失败", message)

    # ------------------------------------------------------------------ 更新
    def _refresh_update_button(self) -> None:
        """根据勾选情况刷新批量更新按钮与表头复选框。"""
        candidates = self.model.update_candidates()
        checked = self.model.checked_results()
        busy = self.worker is not None or self.update_worker is not None
        self.update_btn.setEnabled(bool(checked) and not busy)
        self.update_btn.setText(f"批量更新（{len(checked)}）" if checked else "批量更新")
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
        names = "、".join(r.title for r in results[:5])
        if len(results) > 5:
            names += f" 等 {len(results)} 个模组"

        breaking = [r for r in results
                    if r.change_level in (ChangeLevel.MAJOR, ChangeLevel.MINOR)]
        unclear = [r for r in results if r.change_level is ChangeLevel.UNKNOWN]

        details = ["此操作不可撤销！请务必先手动备份整个游戏实例（至少备份 mods 目录）。",
                   "程序会用官方文件替换旧 jar，旧文件保留为 .bak 备份。"]
        if breaking:
            listed = "、".join(f"{r.title}（{r.state_label}）" for r in breaking[:3])
            if len(breaking) > 3:
                listed += f" 等 {len(breaking)} 个"
            details.insert(0, f"{listed} 属于主版本 / 次版本更新，可能包含破坏性变更"
                              "（配置文件、注册表 ID、数据格式、API 等）。"
                              "建议先点击“最新版本”打开版本发布页阅读发版说明。")
        if unclear:
            details.append(f"另有 {len(unclear)} 个模组无法按版本号判断更新幅度，"
                           "同样建议先查看发版说明。")

        box = QMessageBox(self)
        box.setWindowTitle("确认更新模组")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"将把以下模组更新到最新版本：\n{names}")
        box.setInformativeText("\n\n".join(details))
        confirm = box.addButton("我已备份，开始更新", QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        if breaking or unclear:
            aware = QCheckBox("我已阅读相关发版说明，知晓更新可能带来的后果", box)
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
            url = version_link(result, column)
            if url:
                QDesktopServices.openUrl(QUrl(url))
            return
        if column != "state":
            return
        if not result.can_update:
            if result.has_update:
                self.status_label.setText(
                    f"{result.title}：该文件没有可用的下载直链，请到项目页手动下载")
            return
        if self.update_worker is not None or self.worker is not None:
            return
        if self._confirm_update([result]):
            self._start_update([result])

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
        self.log_view.appendPlainText(f"[更新] 开始更新 {self._update_total} 个模组")
        self.update_worker = UpdateWorker(results, self)
        self.update_worker.item_done.connect(self._on_update_done)
        self.update_worker.log.connect(self._on_log)
        self.update_worker.finished_all.connect(self._on_update_finished)
        self.update_worker.finished.connect(self._on_update_thread_finished)
        self.check_btn.setEnabled(False)
        self.path_edit.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.update_btn.setEnabled(False)
        self.status_label.setText(f"正在更新 1/{self._update_total}…")
        self.update_worker.start()

    def _on_update_done(self, outcome: UpdateOutcome) -> None:
        apply_outcome(outcome.result, outcome)
        self.model.update_result(outcome.result)
        self._update_done += 1
        if outcome.ok:
            self._update_ok += 1
            self.log_view.appendPlainText(f"[更新] {outcome.result.title}：{outcome.message}")
        else:
            self.log_view.appendPlainText(
                f"[更新失败] {outcome.result.title}：{outcome.message}")
        self.progress.setValue(self._update_done)
        self.status_label.setText(
            f"正在更新 {self._update_done}/{self._update_total}"
            f"（成功 {self._update_ok}）")

    def _on_update_finished(self, outcomes) -> None:
        self._apply_filters()
        failed = [item for item in outcomes if not item.ok]
        if self.report is not None:
            self._update_stats(self.report)
        message = f"更新完成：成功 {len(outcomes) - len(failed)} 个"
        if len(outcomes) < self._update_total:
            message += f"，已取消（总计 {self._update_total} 个）"
        if failed:
            message += f"，失败 {len(failed)} 个（详见日志）"
            QMessageBox.warning(self, "部分模组更新失败",
                                "\n".join(f"{item.result.title}：{item.message}"
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
            self.pack_banner.setText(pack.message or "无法获取整合包版本信息")
            self.pack_banner.setStyleSheet("background:#f1f3f5;color:#666e79;")
            return
        if pack.update_available:
            self.pack_banner.setText(
                f"⚠ {pack.message}　最新版发布于 {pack.latest.uploaded_at[:10]}，"
                f"共 {pack.release_count} 个发行版")
            self.pack_banner.setStyleSheet("background:#fff4e0;color:#a35b00;")
        else:
            self.pack_banner.setText(f"✓ {pack.message}")
            self.pack_banner.setStyleSheet("background:#e7f7ec;color:#1c7a3e;")

        index = report.index
        if index and index.usable:
            self.chip_index.setText(
                f"官方清单：{index.pack_version or '未知版本'} / {len(index.filenames)} 项")
            self.chip_index.setToolTip(f"来源：{index.source}")
        else:
            self.chip_index.setText("官方清单：未获取")
            self.chip_index.setToolTip("无法区分整合包自带与手动添加的模组")

        install = report.install
        self.chip_kind.setText(f"类型：{install.kind_label}")
        self.chip_version.setText(f"Minecraft：{install.mc_version or '未识别'}")
        loader = install.loader or "未识别"
        if install.loader_version:
            loader = f"{loader} {install.loader_version}"
        self.chip_loader.setText(f"加载器：{loader}")
        self.chip_pack.setText(f"整合包版本：{install.pack_version or '未识别'}")

    def _update_stats(self, report: Report) -> None:
        manual = report.count_origin(Origin.MANUAL)
        pack = report.count_origin(Origin.PACK)
        unknown_origin = report.count_origin(Origin.UNKNOWN)
        failed = report.count_state(UpdateState.ERROR)
        unknown = report.unknown - failed
        self.stats_label.setText(
            f"共 {report.total} 个模组　"
            f"<span style='color:#d98e04;font-weight:600'>可更新 {report.outdated}</span>　"
            f"<span style='color:#2f9e44;'>已最新 {report.current}</span>　"
            f"<span style='color:#8a8a8a;'>未知 {unknown}</span>　"
            f"<span style='color:#c92a2a;'>查询失败 {failed}</span>　|　"
            f"<span style='color:#1c7ed6;font-weight:600'>手动添加 {manual}</span>　"
            f"整合包自带 {pack}　归属未知 {unknown_origin}"
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
            QDesktopServices.openUrl(QUrl(result.project_url))

    # ------------------------------------------------------------------ 导出
    def _export_csv(self) -> None:
        if self.report is None:
            return
        default = f"atm10-modcheck-{datetime.now():%Y%m%d-%H%M}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "导出检测结果", default, "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["状态", "模组", "归属", "当前版本", "当前发布时间",
                                 "最新版本", "最新发布时间", "来源", "文件名", "modId",
                                 "链接", "备注"])
                for result in self.report.mods:
                    writer.writerow([
                        result.state_label, result.title, result.origin_label,
                        result.installed_version, _csv_date(result.installed_date),
                        result.latest_version, _csv_date(result.latest_date),
                        result.source_label, result.jar.filename, result.jar.mod_id,
                        result.project_url, result.note,
                    ])
        except OSError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self.status_label.setText(f"已导出：{path}")

    # ------------------------------------------------------------------ 其它
    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            dialog.apply_to(self.settings)
            save_settings(self.settings)
            self.pack_edit.setText(self.settings.pack_source)
            if self.settings.last_directory:
                self._inspect_directory(self.settings.last_directory)
            else:
                self._refresh_index_chip()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.update_worker is not None:
            self.update_worker.cancel()
            self.update_worker.wait(5000)
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(3000)
        try:
            self.settings.pack_source = self.pack_edit.text().strip()
            geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self.settings.window_geometry = geometry
            save_settings(self.settings)
        except Exception:
            pass
        super().closeEvent(event)


def _csv_date(value) -> str:
    try:
        return value.astimezone().strftime("%Y-%m-%d") if value else ""
    except (AttributeError, ValueError, OSError):
        return ""


def run_app(argv: list[str]) -> int:
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    font = QFont("Microsoft YaHei UI", 9)
    app.setFont(font)
    window = MainWindow(argv[1] if len(argv) > 1 else "")
    window.show()
    return app.exec()
