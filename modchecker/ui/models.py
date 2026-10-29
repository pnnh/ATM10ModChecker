"""结果表格的 Qt 模型与过滤代理。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor, QFont

from modchecker.models import ModResult, Origin, UpdateState
from modchecker.versioning import compare


@dataclass(frozen=True)
class Column:
    key: str
    title: str
    width: int


COLUMNS: tuple[Column, ...] = (
    Column("state", "状态", 90),
    Column("title", "模组", 300),
    Column("origin", "归属", 100),
    Column("installed", "当前版本", 240),
    Column("latest", "最新版本", 240),
    Column("source", "来源", 100),
    Column("filename", "文件名", 320),
)

_STATE_BRUSH = {
    UpdateState.OUTDATED: QColor("#d98e04"),
    UpdateState.CURRENT: QColor("#2f9e44"),
    UpdateState.UNKNOWN: QColor("#8a8a8a"),
    UpdateState.ERROR: QColor("#c92a2a"),
}
_MANUAL_BRUSH = QColor("#1c7ed6")


class ModTableModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[ModResult] = []

    # ---------------------------------------------------------------- Qt 接口
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        if 0 <= section < len(COLUMNS):
            return COLUMNS[section].title
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        result = self._rows[index.row()]
        column = COLUMNS[index.column()].key

        if role == Qt.DisplayRole:
            return self._text(result, column)
        if role == Qt.ToolTipRole:
            return self._tooltip(result)
        if role == Qt.ForegroundRole and column in ("state", "origin"):
            if column == "origin" and result.origin is Origin.MANUAL:
                return QBrush(_MANUAL_BRUSH)
            return QBrush(_STATE_BRUSH.get(result.state, QColor("#444444")))
        if role == Qt.FontRole and result.jar.disabled:
            font = QFont()
            font.setItalic(True)
            return font
        if role == Qt.TextAlignmentRole and column in ("state", "origin", "source"):
            return int(Qt.AlignCenter)
        if role == Qt.UserRole:
            return result
        return None

    # ---------------------------------------------------------------- 数据
    def set_results(self, results: list[ModResult]) -> None:
        self.beginResetModel()
        self._rows = list(results)
        self.endResetModel()

    def result_at(self, row: int) -> ModResult | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    @staticmethod
    def _text(result: ModResult, column: str) -> str:
        if column == "state":
            return result.state_label
        if column == "title":
            return result.title
        if column == "origin":
            return result.origin_label
        if column == "installed":
            return result.installed_version or "-"
        if column == "latest":
            return result.latest_version or "-"
        if column == "source":
            return result.source_label
        if column == "filename":
            return result.jar.filename + ("（已禁用）" if result.jar.disabled else "")
        return ""

    @staticmethod
    def _tooltip(result: ModResult) -> str:
        lines = [f"文件：{result.jar.filename}"]
        if result.project_title:
            lines.append(f"项目：{result.project_title}")
        if result.installed_version:
            lines.append(f"当前版本：{result.installed_version}")
        if result.latest_version:
            lines.append(f"最新版本：{result.latest_version}")
        if result.jar.mod_id:
            lines.append(f"modId：{result.jar.mod_id}")
        if result.origin_detail:
            lines.append(f"归属依据：{result.origin_detail}")
        if result.note:
            lines.append(f"说明：{result.note}")
        if result.project_url:
            lines.append(f"链接：{result.project_url}")
        return "\n".join(lines)


class ModFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text = ""
        self._origins: set[Origin] = set()
        self._states: set[UpdateState] = set()
        self._only_updates = False
        self.setSortRole(Qt.UserRole + 1)

    # ---------------------------------------------------------------- 过滤器
    def set_text(self, text: str) -> None:
        self._text = (text or "").strip().lower()
        self.invalidateFilter()

    def set_origins(self, origins: set[Origin]) -> None:
        self._origins = origins
        self.invalidateFilter()

    def set_states(self, states: set[UpdateState]) -> None:
        self._states = states
        self.invalidateFilter()

    def set_only_updates(self, enabled: bool) -> None:
        self._only_updates = enabled
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if model is None:
            return True
        result = model.result_at(source_row)
        if result is None:
            return True
        if self._only_updates and not result.has_update:
            return False
        if self._origins and result.origin not in self._origins:
            return False
        if self._states and result.state not in self._states:
            return False
        if self._text:
            haystack = " ".join((result.title, result.jar.filename, result.jar.mod_id,
                                 result.installed_version, result.latest_version)).lower()
            if self._text not in haystack:
                return False
        return True

    # ---------------------------------------------------------------- 排序
    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        column = COLUMNS[left.column()].key
        a = model.result_at(left.row())
        b = model.result_at(right.row())
        if a is None or b is None:
            return False
        if column == "installed":
            return compare(a.installed_version, b.installed_version) < 0
        if column == "latest":
            return compare(a.latest_version, b.latest_version) < 0
        if column == "state":
            return _STATE_SORT.get(a.state, 9) < _STATE_SORT.get(b.state, 9)
        if column == "origin":
            return _ORIGIN_SORT.get(a.origin, 9) < _ORIGIN_SORT.get(b.origin, 9)
        return str(model.data(left, Qt.DisplayRole)).lower() < \
            str(model.data(right, Qt.DisplayRole)).lower()


_STATE_SORT = {UpdateState.OUTDATED: 0, UpdateState.ERROR: 1, UpdateState.UNKNOWN: 2,
               UpdateState.CURRENT: 3}
_ORIGIN_SORT = {Origin.MANUAL: 0, Origin.UNKNOWN: 1, Origin.PACK: 2}
