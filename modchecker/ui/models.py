"""结果表格的 Qt 模型与过滤代理。"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont

from modchecker.models import ModResult, Origin, Source, UpdateState
from modchecker.versioning import compare


@dataclass(frozen=True)
class Column:
    key: str
    title: str
    width: int


COLUMNS: tuple[Column, ...] = (
    Column("select", "", 34),
    Column("state", "状态", 110),
    Column("title", "模组", 260),
    Column("origin", "归属", 100),
    Column("installed", "当前版本", 210),
    Column("installed_date", "当前发布时间", 120),
    Column("latest", "最新版本", 210),
    Column("latest_date", "最新发布时间", 120),
    Column("source", "来源", 100),
    Column("filename", "文件名", 300),
)

_STATE_BRUSH = {
    UpdateState.OUTDATED: QColor("#d98e04"),
    UpdateState.CURRENT: QColor("#2f9e44"),
    UpdateState.UNKNOWN: QColor("#8a8a8a"),
    UpdateState.ERROR: QColor("#c92a2a"),
}
_MANUAL_BRUSH = QColor("#1c7ed6")
_LINK_BRUSH = QColor("#1c62e0")
_LINK_COLUMNS = ("installed", "latest")


def search_link(result: ModResult) -> str:
    """没有具体的版本页时退化为站内搜索（优先 Modrinth，备选 CurseForge）。"""
    keyword = quote(result.title or result.jar.filename)
    if result.source is Source.CURSEFORGE:
        return f"https://www.curseforge.com/minecraft/search?search={keyword}"
    return f"https://modrinth.com/mods?q={keyword}"


def version_link(result: ModResult, column: str) -> str:
    """版本列的点击目标：版本发布页 → 项目页 → 站内搜索。"""
    if column not in _LINK_COLUMNS:
        return ""
    url = result.installed_url if column == "installed" else result.latest_url
    if url:
        return url
    if result.project_url:
        return result.project_url
    return search_link(result)


class ModTableModel(QAbstractTableModel):
    checks_changed = Signal()   # 勾选集合变化（用于刷新“批量更新”按钮与表头）

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[ModResult] = []
        self._checked: set[str] = set()      # 勾选的 jar 路径

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
        if role == Qt.CheckStateRole and column == "select":
            if not result.can_update:
                return None
            key = str(result.jar.path)
            return Qt.Checked if key in self._checked else Qt.Unchecked
        if role == Qt.ToolTipRole:
            return self._tooltip(result, column)
        if role == Qt.ForegroundRole:
            if column in _LINK_COLUMNS and version_link(result, column):
                return QBrush(_LINK_BRUSH)
            if column in ("state", "origin"):
                if column == "origin" and result.origin is Origin.MANUAL:
                    return QBrush(_MANUAL_BRUSH)
                return QBrush(_STATE_BRUSH.get(result.state, QColor("#444444")))
        if role == Qt.FontRole:
            if column in _LINK_COLUMNS:
                font = QFont()
                font.setUnderline(True)
                font.setItalic(result.jar.disabled)
                return font
            if result.jar.disabled:
                font = QFont()
                font.setItalic(True)
                return font
        if role == Qt.TextAlignmentRole and column in ("select", "state", "origin", "source",
                                                       "installed_date", "latest_date"):
            return int(Qt.AlignCenter)
        if role == Qt.UserRole:
            return result
        return None

    def flags(self, index: QModelIndex):
        flags = super().flags(index)
        if index.isValid() and COLUMNS[index.column()].key == "select":
            if self._rows[index.row()].can_update:
                flags |= Qt.ItemIsUserCheckable
            else:
                flags &= ~Qt.ItemIsUserCheckable
        return flags

    def setData(self, index: QModelIndex, value, role=Qt.EditRole) -> bool:  # noqa: N802
        if not index.isValid() or role != Qt.CheckStateRole:
            return False
        if COLUMNS[index.column()].key != "select":
            return False
        result = self._rows[index.row()]
        if not result.can_update:
            return False
        key = str(result.jar.path)
        if Qt.CheckState(value) == Qt.Checked:
            self._checked.add(key)
        else:
            self._checked.discard(key)
        self.dataChanged.emit(index, index, [Qt.CheckStateRole])
        self.checks_changed.emit()
        return True

    # ---------------------------------------------------------------- 数据
    def set_results(self, results: list[ModResult]) -> None:
        self.beginResetModel()
        self._rows = list(results)
        self._prune_checked()
        self.endResetModel()
        self.checks_changed.emit()

    def append_result(self, result: ModResult) -> None:
        """流式追加一行；最终排序在完整报告生成后统一做。"""
        row = len(self._rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self._rows.append(result)
        self.endInsertRows()

    def update_result(self, result: ModResult) -> None:
        """刷新单行（更新模组后调用）。"""
        before = set(self._checked)
        for row, item in enumerate(self._rows):
            if item is result:
                self._prune_checked()
                self.dataChanged.emit(self.index(row, 0),
                                      self.index(row, len(COLUMNS) - 1))
                if before != self._checked:
                    self.checks_changed.emit()
                return

    def _prune_checked(self) -> None:
        """只保留仍然存在且仍可更新的勾选（更新成功后路径与状态都会变）。"""
        valid = {str(r.jar.path) for r in self._rows if r.can_update}
        self._checked &= valid

    # ---------------------------------------------------------------- 勾选
    def checked_results(self) -> list[ModResult]:
        return [r for r in self._rows if r.can_update and str(r.jar.path) in self._checked]

    def update_candidates(self) -> list[ModResult]:
        return [r for r in self._rows if r.can_update]

    def set_all_updates(self, checked: bool) -> None:
        """表头复选框：全选 / 全不选所有“可更新”的模组。"""
        self._checked = ({str(r.jar.path) for r in self._rows if r.can_update}
                         if checked else set())
        self._emit_check_changes()

    def clear_checked(self) -> None:
        if self._checked:
            self._checked.clear()
            self._emit_check_changes()

    def _emit_check_changes(self) -> None:
        if self._rows:
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(len(self._rows) - 1, 0),
                                  [Qt.CheckStateRole])
        self.checks_changed.emit()

    def result_at(self, row: int) -> ModResult | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    @staticmethod
    def _text(result: ModResult, column: str) -> str:
        if column == "select":
            return ""
        if column == "state":
            return result.state_label
        if column == "title":
            return result.title
        if column == "origin":
            return result.origin_label
        if column == "installed":
            return result.installed_version or "-"
        if column == "installed_date":
            return ModTableModel._fmt_date(result.installed_date)
        if column == "latest":
            return result.latest_version or "-"
        if column == "latest_date":
            return ModTableModel._fmt_date(result.latest_date)
        if column == "source":
            return result.source_label
        if column == "filename":
            return result.jar.filename + ("（已禁用）" if result.jar.disabled else "")
        return ""

    @staticmethod
    def _fmt_date(value) -> str:
        if not value:
            return "-"
        try:
            return value.astimezone().strftime("%Y-%m-%d")
        except (AttributeError, ValueError, OSError):
            return "-"

    @staticmethod
    def _tooltip(result: ModResult, column: str = "") -> str:
        lines: list[str] = []
        if column == "state" and result.can_update:
            lines.append("点击可更新到最新版本（会先弹窗确认，操作不可撤销）")
        if column in _LINK_COLUMNS:
            own_url = result.installed_url if column == "installed" else result.latest_url
            lines.append("点击在浏览器打开版本发布页，查看发版说明" if own_url
                         else "点击在浏览器打开项目页面 / 站内搜索")
        if result.state is UpdateState.ERROR and result.note:
            lines.append(f"失败原因：{result.note}")
        lines.append(f"文件：{result.jar.filename}")
        if result.project_title:
            lines.append(f"项目：{result.project_title}")
        if result.installed_version:
            lines.append(f"当前版本：{result.installed_version}")
        if result.installed_date:
            lines.append(f"当前发布时间：{result.installed_date.astimezone():%Y-%m-%d %H:%M}")
        if result.latest_version:
            lines.append(f"最新版本：{result.latest_version}")
        if result.latest_date:
            lines.append(f"最新发布时间：{result.latest_date.astimezone():%Y-%m-%d %H:%M}")
        if result.jar.mod_id:
            lines.append(f"modId：{result.jar.mod_id}")
        if result.origin_detail:
            lines.append(f"归属依据：{result.origin_detail}")
        if result.note and not (result.state is UpdateState.ERROR
                                and result.note.startswith("查询失败")):
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
        if column == "installed_date":
            return _date_key(a.installed_date) < _date_key(b.installed_date)
        if column == "latest_date":
            return _date_key(a.latest_date) < _date_key(b.latest_date)
        if column == "state":
            return _STATE_SORT.get(a.state, 9) < _STATE_SORT.get(b.state, 9)
        if column == "origin":
            return _ORIGIN_SORT.get(a.origin, 9) < _ORIGIN_SORT.get(b.origin, 9)
        return str(model.data(left, Qt.DisplayRole)).lower() < \
            str(model.data(right, Qt.DisplayRole)).lower()


_STATE_SORT = {UpdateState.ERROR: 0, UpdateState.OUTDATED: 1, UpdateState.UNKNOWN: 2,
               UpdateState.CURRENT: 3}
_ORIGIN_SORT = {Origin.MANUAL: 0, Origin.UNKNOWN: 1, Origin.PACK: 2}


def _date_key(value) -> float:
    """发布时间排序键；缺失时间统一排在最前（升序时即为最旧）。"""
    try:
        return value.timestamp()
    except (AttributeError, ValueError, OSError):
        return 0.0
