"""应用级路径与用户设置（settings.json）持久化。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from modchecker import APP_ID

# ATM10 固定常量（整合包本身不会变）
ATM10_SLUG = "all-the-mods-10"
ATM10_CF_ID = 925200
DEFAULT_GAME_VERSION = "1.21.1"
DEFAULT_LOADER = "neoforge"


def _base_dir(env: str, fallback: str) -> Path:
    root = os.environ.get(env)
    path = Path(root) if root else Path.home() / fallback
    return path / APP_ID


def config_dir() -> Path:
    path = _base_dir("APPDATA", "AppData/Roaming")
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = _base_dir("LOCALAPPDATA", "AppData/Local") / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = config_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


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
    pack_zip: str = ""              # 可选的整合包 zip（本地读取 manifest.json）
    verify_official: bool = True    # 是否构建官方模组索引用于分类
    window_geometry: str = ""

    def resolved(self) -> tuple[str, str]:
        return (
            (self.game_version or DEFAULT_GAME_VERSION).strip(),
            (self.loader or DEFAULT_LOADER).strip().lower(),
        )


_SETTINGS_FILE = config_dir() / "settings.json"


def load_settings() -> Settings:
    if not _SETTINGS_FILE.exists():
        return Settings()
    try:
        raw = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in raw.items() if k in known})


def save_settings(settings: Settings) -> None:
    tmp = _SETTINGS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_SETTINGS_FILE)
