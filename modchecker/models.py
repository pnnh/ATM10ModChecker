"""领域模型：扫描结果、识别结果与检测报告。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from modchecker.i18n import t


class InstallKind(str, Enum):
    CLIENT = "client"
    SERVER = "server"
    UNKNOWN = "unknown"


class Source(str, Enum):
    MODRINTH = "modrinth"
    CURSEFORGE = "curseforge"
    NONE = "none"


class Origin(str, Enum):
    PACK = "pack"        # 整合包自带
    MANUAL = "manual"    # 手动添加
    UNKNOWN = "unknown"  # 无法判定


class UpdateState(str, Enum):
    OUTDATED = "outdated"  # 有新版本
    CURRENT = "current"    # 已是最新
    UNKNOWN = "unknown"    # 无法确定（未识别 / 无可用版本）
    ERROR = "error"        # 查询失败


class ChangeLevel(str, Enum):
    """“可更新”的细化程度，按语义化版本号判断。"""

    NONE = ""                  # 不是可更新状态
    MAJOR = "major"            # 1.x.x -> 2.x.x
    MINOR = "minor"            # 1.2.x -> 1.3.x
    PATCH = "patch"            # 1.2.3 -> 1.2.4
    BUILD = "build"            # 第四段及以后（构建号 / 打包号）
    PRERELEASE = "prerelease"  # 本地走 beta/alpha 通道
    UNKNOWN = "unknown"        # 无法按版本号细分


SOURCE_LABELS = {
    Source.MODRINTH: "Modrinth",
    Source.CURSEFORGE: "CurseForge",
    Source.NONE: "source.none",
}

ORIGIN_LABELS = {
    Origin.PACK: "origin.pack",
    Origin.MANUAL: "origin.manual",
    Origin.UNKNOWN: "origin.unknown",
}

STATE_LABELS = {
    UpdateState.OUTDATED: "state.outdated",
    UpdateState.CURRENT: "state.current",
    UpdateState.UNKNOWN: "state.unknown",
    UpdateState.ERROR: "state.error",
}

CHANGE_LABELS = {
    ChangeLevel.MAJOR: "change.major",
    ChangeLevel.MINOR: "change.minor",
    ChangeLevel.PATCH: "change.patch",
    ChangeLevel.BUILD: "change.build",
    ChangeLevel.PRERELEASE: "change.prerelease",
    ChangeLevel.UNKNOWN: "change.unknown",
}

KIND_LABELS = {
    InstallKind.CLIENT: "kind.client",
    InstallKind.SERVER: "kind.server",
    InstallKind.UNKNOWN: "kind.unknown",
}


@dataclass
class JarEntry:
    """mods 目录里的一个 jar。"""

    path: Path
    filename: str
    disabled: bool
    size: int
    mtime: float
    sha1: str = ""
    mod_id: str = ""
    display_name: str = ""
    jar_version: str = ""

    @property
    def label(self) -> str:
        return self.display_name or self.mod_id or self.filename


@dataclass
class ModResult:
    """单个模组的检测结果。"""

    jar: JarEntry
    source: Source = Source.NONE
    project_id: str = ""
    project_title: str = ""
    project_url: str = ""
    installed_version: str = ""
    installed_date: datetime | None = None
    installed_url: str = ""          # 当前版本的发版页面
    latest_version: str = ""
    latest_date: datetime | None = None
    latest_url: str = ""             # 最新版本的发版页面（点开可看 changelog）
    latest_filename: str = ""
    download_url: str = ""
    download_filename: str = ""
    download_sha1: str = ""
    download_size: int = 0
    state: UpdateState = UpdateState.UNKNOWN
    change_level: ChangeLevel = ChangeLevel.NONE
    origin: Origin = Origin.UNKNOWN
    origin_detail: str = ""
    note: str = ""
    note_is_error: bool = False      # note 是失败原因（用于 tooltip 排版，避免靠文案前缀判断）

    @property
    def has_update(self) -> bool:
        return self.state is UpdateState.OUTDATED

    @property
    def can_update(self) -> bool:
        """有更新且拿到了可下载的地址（CurseForge 部分文件不提供直链）。"""
        return self.has_update and bool(self.download_url) and bool(self.download_filename)

    @property
    def title(self) -> str:
        return self.project_title or self.jar.label

    @property
    def state_label(self) -> str:
        if self.state is UpdateState.OUTDATED:
            return t(CHANGE_LABELS.get(self.change_level) or STATE_LABELS[self.state])
        return t(STATE_LABELS[self.state])

    @property
    def origin_label(self) -> str:
        return t(ORIGIN_LABELS[self.origin])

    @property
    def source_label(self) -> str:
        # Modrinth / CurseForge 是专有名词，文案表里没有对应 key 时原样返回
        return t(SOURCE_LABELS[self.source])


@dataclass
class InstallInfo:
    """安装目录探测结果。"""

    root: Path
    game_dir: Path
    mods_dir: Path
    kind: InstallKind = InstallKind.UNKNOWN
    mc_version: str = ""
    loader: str = ""
    loader_version: str = ""
    pack_name: str = ""
    pack_version: str = ""
    metadata_path: str = ""
    jar_total: int = 0

    @property
    def kind_label(self) -> str:
        return t(KIND_LABELS.get(self.kind, "kind.unknown"))


@dataclass
class PackRelease:
    """ATM10 的一个正式发行版。"""

    file_id: int
    display: str        # 例如 "All the Mods 10-8.3"
    filename: str       # 例如 "All the Mods 10-8.3.zip"
    version: str        # 例如 "8.3"
    release_type: str = ""
    uploaded_at: str = ""
    filesize: int = 0
    game_versions: list[str] = field(default_factory=list)
    download_url: str = ""


@dataclass
class PackStatus:
    """整合包整体更新状态。"""

    installed_version: str = ""
    latest: PackRelease | None = None
    update_available: bool = False
    release_count: int = 0
    message: str = ""


@dataclass
class OfficialIndex:
    """某个整合包版本的官方模组清单（用于区分自带/手动）。"""

    pack_version: str = ""
    mc_version: str = ""
    loader: str = ""
    source: str = ""            # 索引来源描述，便于界面展示
    filenames: set[str] = field(default_factory=set)
    sha1s: set[str] = field(default_factory=set)
    project_files: dict[str, str] = field(default_factory=dict)  # projectID -> fileName
    declared: int = 0           # manifest 中声明的模组数
    resolved: int = 0           # 成功解析到文件名的数量
    complete: bool = True

    @property
    def usable(self) -> bool:
        return bool(self.filenames or self.sha1s or self.project_files)


@dataclass
class Report:
    """一次完整检测的结果。"""

    install: InstallInfo
    mods: list[ModResult] = field(default_factory=list)
    pack: PackStatus = field(default_factory=PackStatus)
    index: OfficialIndex | None = None
    warnings: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    query_errors: int = 0

    # ---- 统计
    @property
    def total(self) -> int:
        return len(self.mods)

    def count_state(self, state: UpdateState) -> int:
        return sum(1 for m in self.mods if m.state is state)

    def count_origin(self, origin: Origin) -> int:
        return sum(1 for m in self.mods if m.origin is origin)

    @property
    def outdated(self) -> int:
        return self.count_state(UpdateState.OUTDATED)

    @property
    def current(self) -> int:
        return self.count_state(UpdateState.CURRENT)

    @property
    def unknown(self) -> int:
        return self.count_state(UpdateState.UNKNOWN) + self.count_state(UpdateState.ERROR)
