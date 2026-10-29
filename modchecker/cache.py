"""磁盘 JSON 缓存：网络查询结果按需缓存，减少重复请求与封禁风险。"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class JsonCache:
    """单个 JSON 文件缓存，线程安全。

    ``ttl`` 为秒，``None`` 表示永不过期。
    """

    def __init__(self, path: Path, ttl: float | None = None) -> None:
        self.path = path
        self.ttl = ttl
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = raw
        except (OSError, ValueError):
            self._data = {}

    def get(self, key: str) -> Any:
        with self._lock:
            self._ensure_loaded()
            item = self._data.get(key)
        if not isinstance(item, dict) or "v" not in item:
            return None
        if self.ttl is not None and time.time() - float(item.get("t", 0)) > self.ttl:
            return None
        return item["v"]

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._ensure_loaded()
            self._data[key] = {"t": time.time(), "v": value}

    def update(self, mapping: dict[str, Any]) -> None:
        with self._lock:
            self._ensure_loaded()
            now = time.time()
            for key, value in mapping.items():
                self._data[key] = {"t": now, "v": value}

    def prune(self) -> None:
        if self.ttl is None:
            return
        with self._lock:
            self._ensure_loaded()
            limit = time.time() - self.ttl
            self._data = {k: v for k, v in self._data.items()
                          if isinstance(v, dict) and float(v.get("t", 0)) >= limit}

    def flush(self) -> None:
        with self._lock:
            self._ensure_loaded()
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.path)
            except OSError:
                pass

    def clear(self) -> None:
        with self._lock:
            self._data = {}
            self._loaded = True
        self.flush()


DAY = 86400.0


class CacheStore:
    """按用途划分的缓存集合。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        # sha1 -> Modrinth version 对象（已发布的版本不会变，缓存久一些）
        self.modrinth_versions = JsonCache(root / "modrinth_versions.json", ttl=14 * DAY)
        # project id -> project 对象
        self.modrinth_projects = JsonCache(root / "modrinth_projects.json", ttl=7 * DAY)
        # "project|game|loader" -> 版本列表
        self.modrinth_listings = JsonCache(root / "modrinth_listings.json", ttl=6 * 3600.0)
        # "mod:file" -> CF 文件对象
        self.cf_files = JsonCache(root / "curseforge_files.json", ttl=7 * DAY)
        # "mod" -> CF 项目对象
        self.cf_mods = JsonCache(root / "curseforge_mods.json", ttl=7 * DAY)
        # 项目文件列表（含筛选条件）
        self.cf_listings = JsonCache(root / "curseforge_listings.json", ttl=6 * 3600.0)
        # 搜索结果（关键词搜索开销大，且同一词会多次用到）
        self.cf_search = JsonCache(root / "curseforge_search.json", ttl=2 * DAY)
        # sha1 -> 识别结果（jar 内容不会变）
        self.jar_identity = JsonCache(root / "jar_identity.json", ttl=None)
        self.sha1_index = JsonCache(root / "sha1_index.json", ttl=None)  # 路径 -> sha1
        # 整合包发行版列表
        self.pack_releases = JsonCache(root / "pack_releases.json", ttl=6 * 3600.0)
        # 官方模组索引（按整合包版本）
        self.official_index = JsonCache(root / "official_index.json", ttl=None)

    def caches(self) -> list[JsonCache]:
        return [self.modrinth_versions, self.modrinth_projects, self.modrinth_listings,
                self.cf_files, self.cf_mods, self.cf_listings, self.cf_search, self.jar_identity,
                self.sha1_index, self.pack_releases, self.official_index]

    def flush(self) -> None:
        for cache in self.caches():
            cache.flush()

    def clear_all(self) -> None:
        for cache in self.caches():
            cache.clear()
