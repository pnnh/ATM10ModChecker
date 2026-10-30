"""应用级路径与用户设置（settings.json）持久化。

所有运行时数据（设置、缓存、日志）统一放在程序所在目录的 ``.ATM10ModChecker`` 下，
源码运行时是仓库根目录，打包后是 exe 所在目录 —— 用户删掉这个文件夹即完成卸载。
只有该位置不可写（只读目录、沙箱）时才退回用户目录，见 ``logging_setup.data_dir``。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from modchecker import APP_ID
from modchecker.logging_setup import data_dir, get_logger

log = get_logger("config")

# ATM10 固定常量（整合包本身不会变）
ATM10_SLUG = "all-the-mods-10"
ATM10_CF_ID = 925200
DEFAULT_GAME_VERSION = "1.21.1"
DEFAULT_LOADER = "neoforge"


def _ensure(directory: Path) -> Path:
    """确保目录存在；建不出来只记日志，后续读写各自兜底。"""
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("无法创建目录 %s：%s", directory, exc)
    return directory


def config_dir() -> Path:
    """设置目录：程序所在目录下的 ``.ATM10ModChecker``。"""
    return _ensure(data_dir())


def cache_dir() -> Path:
    """接口响应缓存目录：``<data_dir>/cache``。"""
    return _ensure(data_dir() / "cache")


def log_dir() -> Path:
    """日志目录：``<data_dir>/logs``（与设置、缓存同一个根目录）。"""
    from modchecker.logging_setup import log_directory

    return log_directory()


def _legacy_settings() -> Path:
    """1.1 及更早版本的设置位置（用户目录），仅用于一次性迁移。"""
    if sys.platform == "win32":
        root = os.environ.get("APPDATA")
        base = Path(root) if root else Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        root = os.environ.get("XDG_CONFIG_HOME")
        base = Path(root) if root else Path.home() / ".config"
    return base / APP_ID / "settings.json"


def _migrate_legacy_settings(target: Path) -> None:
    """把旧版留在用户目录的设置搬过来一次，免得升级后要重配。"""
    legacy = _legacy_settings()
    if target.exists() or not legacy.exists():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(legacy, target)
    except OSError as exc:
        log.warning("迁移旧设置失败（%s）：%s", legacy, exc)
        return
    log.info("已把设置从旧位置迁移过来：%s -> %s", legacy, target)


@dataclass
class Settings:
    """用户可调参数。空字符串表示“自动识别”。"""

    last_directory: str = ""
    game_version: str = ""          # 空 = 自动探测
    loader: str = ""                # 空 = 自动探测
    use_modrinth: bool = True
    use_curseforge: bool = True
    curseforge_api_key: str = ""    # 留空则使用公共只读代理
    include_disabled: bool = False  # 是否扫描 *.jar.disabled
    concurrency: int = 6
    language: str = "auto"          # auto / en / zh
    # 用户指定的整合包原包：原始 zip，或原始 zip 解压后的纯净目录（可选）
    pack_source: str = ""
    verify_official: bool = True    # 是否构建官方模组索引用于分类
    window_geometry: str = ""

    def resolved(self) -> tuple[str, str]:
        return (
            (self.game_version or DEFAULT_GAME_VERSION).strip(),
            (self.loader or DEFAULT_LOADER).strip().lower(),
        )


_SETTINGS_FILE = config_dir() / "settings.json"
_migrate_legacy_settings(_SETTINGS_FILE)


def settings_path() -> Path:
    return _SETTINGS_FILE


def load_settings() -> Settings:
    if not _SETTINGS_FILE.exists():
        return Settings()
    try:
        raw = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # 配置损坏不该拦住启动，退回默认值并留下日志
        log.warning("读取设置失败，改用默认设置：%s", exc)
        return Settings()
    if not isinstance(raw, dict):
        log.warning("设置文件内容不是对象，改用默认设置")
        return Settings()
    known = {f.name for f in fields(Settings)}
    data = {k: v for k, v in raw.items() if k in known}
    # 兼容旧版设置里的 pack_zip 字段
    legacy = raw.get("pack_zip")
    if not data.get("pack_source") and isinstance(legacy, str):
        data["pack_source"] = legacy
    try:
        return Settings(**data)
    except TypeError as exc:          # 字段类型不匹配等
        log.warning("设置内容无法应用，改用默认设置：%s", exc)
        return Settings()


def save_settings(settings: Settings) -> bool:
    """原子写回设置；失败只记日志，不打断用户操作。"""
    tmp = _SETTINGS_FILE.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(_SETTINGS_FILE)
        return True
    except OSError as exc:
        log.error("保存设置失败（%s）：%s", _SETTINGS_FILE, exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
