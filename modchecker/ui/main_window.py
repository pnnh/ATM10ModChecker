"""主窗口。"""

from __future__ import annotations

import csv
import base64
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QTableView, QVBoxLayout, QWidget)

from modchecker import APP_NAME, __version__, scanner
from modchecker.appconfig import Settings, load_settings, save_settings
from modchecker.checker import CheckOptions
from modchecker.models import Origin, Report, UpdateState
from modchecker.ui.models import COLUMNS, ModFilterProxy, ModTableModel
from modchecker.ui.settings_dialog import SettingsDialog, zip_path_or_none
from modchecker.ui.worker import CheckWorker

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


class MainWindow(QMainWindow):
    def __init__(self, initial_dir: str = "") -> None:
        super().__init__()
        self.settings: Settings = load_settings()
        self.report: Report | None = None
        self.worker: CheckWorker | None = None

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
        subtitle = QLabel("只检测、不下载：比对 mods 目录中的 jar 与 Modrinth / CurseForge 上的最新版本，"
                          "并区分整合包自带与手动添加的模组。")
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
        self.table.doubleClicked.connect(self._open_project)
        header_view = self.table.horizontalHeader()
        header_view.setStretchLastSection(True)
        for position, column in enumerate(COLUMNS):
            self.table.setColumnWidth(position, column.width)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
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
        self.status_label.setText(f"已识别 mods 目录：{info.mods_dir}（{info.jar_total} 个 jar）")
        self.settings.last_directory = str(path)
        save_settings(self.settings)

    # ------------------------------------------------------------------ 检测
    def _build_options(self) -> CheckOptions | None:
        directory = self.path_edit.text().strip()
        if not directory or not Path(directory).is_dir():
            QMessageBox.warning(self, "需要安装目录", "请先选择 ATM10 的安装目录。")
            return None
        if not self.settings.use_modrinth and not self.settings.use_curseforge:
            QMessageBox.warning(self, "没有可用的数据源", "请至少启用一个数据源（Modrinth 或 CurseForge）。")
            return None
        return CheckOptions(
            game_version=self.settings.game_version.strip(),
            loader=self.settings.loader.strip(),
            include_disabled=self.settings.include_disabled,
            use_modrinth=self.settings.use_modrinth,
            use_curseforge=self.settings.use_curseforge,
            cf_api_key=self.settings.curseforge_api_key,
            concurrency=max(1, self.settings.concurrency),
            verify_official=self.settings.verify_official,
            pack_zip=zip_path_or_none(self.settings),
        )

    def _start_check(self) -> None:
        if self.worker is not None:
            return
        directory = self.path_edit.text().strip()
        options = self._build_options()
        if options is None:
            return
        self.report = None
        self.model.set_results([])
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
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_thread_finished)
        self.worker.start()

    def _cancel_check(self) -> None:
        if self.worker is not None:
            self.cancel_btn.setEnabled(False)
            self.status_label.setText("正在取消…")
            self.worker.cancel()

    def _set_running(self, running: bool) -> None:
        self.check_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.path_edit.setEnabled(not running)

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

    def _on_thread_finished(self) -> None:
        self._set_running(False)
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None

    def _on_finished(self, report: Report) -> None:
        self.report = report
        self.model.set_results(report.mods)
        self.progress.setValue(100)
        self.export_btn.setEnabled(bool(report.mods))
        self._apply_filters()
        self._update_stats(report)
        self._update_pack_banner(report)
        self.status_label.setText(f"检测完成，用时 {report.elapsed:.1f} 秒")
        for warning in report.warnings:
            self.log_view.appendPlainText(f"[警告] {warning}")
        if report.query_errors:
            self.log_view.appendPlainText(f"[提示] {report.query_errors} 个模组查询失败，可稍后重试。")

    def _on_cancelled(self) -> None:
        self.status_label.setText("已取消")
        self.progress.setValue(0)
        if self.report is None:
            self.stats_label.setText("—")

    def _on_failed(self, message: str) -> None:
        self.status_label.setText("检测失败")
        self.progress.setValue(0)
        QMessageBox.critical(self, "检测失败", message)

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
        self.stats_label.setText(
            f"共 {report.total} 个模组　"
            f"<span style='color:#d98e04;font-weight:600'>可更新 {report.outdated}</span>　"
            f"<span style='color:#2f9e44;'>已最新 {report.current}</span>　"
            f"<span style='color:#8a8a8a;'>未知 {report.unknown}</span>　|　"
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
                writer.writerow(["状态", "模组", "归属", "当前版本", "最新版本", "来源",
                                 "文件名", "modId", "链接", "备注"])
                for result in self.report.mods:
                    writer.writerow([
                        result.state_label, result.title, result.origin_label,
                        result.installed_version, result.latest_version, result.source_label,
                        result.jar.filename, result.jar.mod_id, result.project_url,
                        result.note,
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
            if self.settings.last_directory:
                self._inspect_directory(self.settings.last_directory)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(3000)
        try:
            geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self.settings.window_geometry = geometry
            save_settings(self.settings)
        except Exception:
            pass
        super().closeEvent(event)


def run_app(argv: list[str]) -> int:
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    font = QFont("Microsoft YaHei UI", 9)
    app.setFont(font)
    window = MainWindow(argv[1] if len(argv) > 1 else "")
    window.show()
    return app.exec()
