"""设置对话框：版本基准、数据源、CurseForge Key、并发度等。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)

from modchecker.appconfig import Settings


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("高级设置")
        self.setMinimumWidth(560)
        self._settings = settings

        layout = QVBoxLayout(self)

        version_box = QGroupBox("版本基准（留空则自动识别）")
        version_form = QFormLayout(version_box)
        self.mc_edit = QLineEdit(settings.game_version)
        self.mc_edit.setPlaceholderText("例如 1.21.1")
        self.loader_combo = QComboBox()
        self.loader_combo.addItems(["", "neoforge", "forge", "fabric", "quilt"])
        index = self.loader_combo.findText(settings.loader)
        self.loader_combo.setCurrentIndex(max(0, index))
        version_form.addRow("Minecraft 版本：", self.mc_edit)
        version_form.addRow("模组加载器：", self.loader_combo)
        version_form.addRow(QLabel("“最新版本”只在匹配的 MC 版本 + 加载器下查找，避免误报不兼容的更新。"))
        layout.addWidget(version_box)

        source_box = QGroupBox("数据源")
        source_form = QFormLayout(source_box)
        self.modrinth_check = QCheckBox("启用 Modrinth（无需 API Key，覆盖约 60%）")
        self.modrinth_check.setChecked(settings.use_modrinth)
        self.curseforge_check = QCheckBox("启用 CurseForge（补全识别与最新版本，覆盖率接近 100%）")
        self.curseforge_check.setChecked(settings.use_curseforge)
        self.key_edit = QLineEdit(settings.curseforge_api_key)
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("留空则使用公共只读代理 api.curse.tools")
        self.verify_check = QCheckBox("检测时构建官方模组清单（用于区分整合包自带 / 手动添加）")
        self.verify_check.setChecked(settings.verify_official)
        source_form.addRow(self.modrinth_check)
        source_form.addRow(self.curseforge_check)
        source_form.addRow("CurseForge API Key：", self.key_edit)
        source_form.addRow(self.verify_check)
        layout.addWidget(source_box)

        scan_box = QGroupBox("扫描")
        scan_form = QFormLayout(scan_box)
        self.disabled_check = QCheckBox("同时检测被禁用的模组（*.jar.disabled）")
        self.disabled_check.setChecked(settings.include_disabled)
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 16)
        self.concurrency_spin.setValue(max(1, min(16, settings.concurrency)))
        scan_form.addRow(self.disabled_check)
        scan_form.addRow("网络并发数：", self.concurrency_spin)
        layout.addWidget(scan_box)

        pack_box = QGroupBox("整合包原包（可选，用于精确判断自带 / 手动）")
        pack_layout = QHBoxLayout(pack_box)
        self.pack_edit = QLineEdit(settings.pack_source)
        self.pack_edit.setPlaceholderText("整合包原始 zip，或原始 zip 解压后的纯净目录")
        pick_zip = QPushButton("选择 zip…")
        pick_zip.clicked.connect(self._pick_zip)
        pick_dir = QPushButton("选择目录…")
        pick_dir.clicked.connect(self._pick_dir)
        pack_layout.addWidget(self.pack_edit)
        pack_layout.addWidget(pick_zip)
        pack_layout.addWidget(pick_dir)
        layout.addWidget(pack_box)

        hint = QLabel("提示：官方清单也会缓存，同一整合包版本只需解析一次；"
                      "清空配置目录下的 cache 可强制刷新。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

    def _pick_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择整合包 zip", "", "Zip 文件 (*.zip)")
        if path:
            self.pack_edit.setText(path)

    def _pick_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择整合包解压后的目录")
        if path:
            self.pack_edit.setText(path)

    def apply_to(self, settings: Settings) -> Settings:
        settings.game_version = self.mc_edit.text().strip()
        settings.loader = self.loader_combo.currentText().strip()
        settings.use_modrinth = self.modrinth_check.isChecked()
        settings.use_curseforge = self.curseforge_check.isChecked()
        settings.curseforge_api_key = self.key_edit.text().strip()
        settings.verify_official = self.verify_check.isChecked()
        settings.include_disabled = self.disabled_check.isChecked()
        settings.concurrency = int(self.concurrency_spin.value())
        settings.pack_source = self.pack_edit.text().strip()
        return settings


def pack_source_or_none(settings: Settings) -> Path | None:
    """整合包原包路径（zip 文件或解压目录），无效时返回 ``None``。"""
    text = (settings.pack_source or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    return path if path.is_file() or path.is_dir() else None
