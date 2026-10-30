"""设置对话框：界面语言、版本基准、数据源、CurseForge Key、并发度等。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)

from modchecker.appconfig import Settings
from modchecker.i18n import LANGUAGE_NATIVE_NAMES, LANGUAGES, t


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("settings.title"))
        self.setMinimumWidth(560)
        self._settings = settings

        layout = QVBoxLayout(self)

        # ---- 语言：切换后由主窗口立即重建文案，无需重启
        language_box = QGroupBox(t("settings.language_box"))
        language_form = QFormLayout(language_box)
        self.language_combo = QComboBox()
        for code in LANGUAGES:
            label = t("settings.language_auto") if code == "auto" else LANGUAGE_NATIVE_NAMES[code]
            self.language_combo.addItem(label, code)
        index = self.language_combo.findData(settings.language or "auto")
        self.language_combo.setCurrentIndex(max(0, index))
        language_form.addRow(t("settings.language_label"), self.language_combo)
        layout.addWidget(language_box)

        version_box = QGroupBox(t("settings.version_box"))
        version_form = QFormLayout(version_box)
        self.mc_edit = QLineEdit(settings.game_version)
        self.mc_edit.setPlaceholderText(t("settings.mc_placeholder"))
        self.loader_combo = QComboBox()
        self.loader_combo.addItems(["", "neoforge", "forge", "fabric", "quilt"])
        index = self.loader_combo.findText(settings.loader)
        self.loader_combo.setCurrentIndex(max(0, index))
        version_form.addRow(t("settings.mc_label"), self.mc_edit)
        version_form.addRow(t("settings.loader_label"), self.loader_combo)
        version_form.addRow(QLabel(t("settings.version_hint")))
        layout.addWidget(version_box)

        source_box = QGroupBox(t("settings.source_box"))
        source_form = QFormLayout(source_box)
        self.modrinth_check = QCheckBox(t("settings.modrinth"))
        self.modrinth_check.setChecked(settings.use_modrinth)
        self.curseforge_check = QCheckBox(t("settings.curseforge"))
        self.curseforge_check.setChecked(settings.use_curseforge)
        self.key_edit = QLineEdit(settings.curseforge_api_key)
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText(t("settings.key_placeholder"))
        self.verify_check = QCheckBox(t("settings.verify"))
        self.verify_check.setChecked(settings.verify_official)
        source_form.addRow(self.modrinth_check)
        source_form.addRow(self.curseforge_check)
        source_form.addRow(t("settings.key_label"), self.key_edit)
        source_form.addRow(self.verify_check)
        layout.addWidget(source_box)

        scan_box = QGroupBox(t("settings.scan_box"))
        scan_form = QFormLayout(scan_box)
        self.disabled_check = QCheckBox(t("settings.disabled"))
        self.disabled_check.setChecked(settings.include_disabled)
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 16)
        self.concurrency_spin.setValue(max(1, min(16, settings.concurrency)))
        scan_form.addRow(self.disabled_check)
        scan_form.addRow(t("settings.concurrency"), self.concurrency_spin)
        layout.addWidget(scan_box)

        pack_box = QGroupBox(t("settings.pack_box"))
        pack_layout = QHBoxLayout(pack_box)
        self.pack_edit = QLineEdit(settings.pack_source)
        self.pack_edit.setPlaceholderText(t("settings.pack_placeholder"))
        pick_zip = QPushButton(t("settings.pick_zip"))
        pick_zip.clicked.connect(self._pick_zip)
        pick_dir = QPushButton(t("settings.pick_dir"))
        pick_dir.clicked.connect(self._pick_dir)
        pack_layout.addWidget(self.pack_edit)
        pack_layout.addWidget(pick_zip)
        pack_layout.addWidget(pick_dir)
        layout.addWidget(pack_box)

        hint = QLabel(t("settings.hint"))
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
        path, _ = QFileDialog.getOpenFileName(self, t("dialog.file.choose_pack_zip"), "",
                                              t("dialog.file.zip_filter"))
        if path:
            self.pack_edit.setText(path)

    def _pick_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, t("dialog.file.choose_pack_dir"))
        if path:
            self.pack_edit.setText(path)

    def apply_to(self, settings: Settings) -> Settings:
        settings.language = str(self.language_combo.currentData() or "auto")
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
