"""Modrinth API 客户端（无需 API Key）。

关键接口：
* ``POST /v2/version_files``          —— 按 sha1 精确识别 jar（版本 + 项目）
* ``POST /v2/version_files/update``   —— 批量取得“最新可用版本”（可按 MC 版本/加载器过滤）
* ``GET  /v2/projects?ids=[...]``     —— 批量取项目信息
"""

from __future__ import annotations

import urllib.parse
from typing import Callable, Sequence

from modchecker.cache import CacheStore
from modchecker.net import HttpClient

BASE = "https://api.modrinth.com/v2"
_BATCH = 400
_PROJECT_BATCH = 50

Logger = Callable[[str], None]


def _chunks(items: Sequence[str], size: int) -> list[list[str]]:
    return [list(items[i:i + size]) for i in range(0, len(items), size)]


class ModrinthProvider:
    def __init__(self, http: HttpClient, cache: CacheStore, log: Logger | None = None) -> None:
        self.http = http
        self.cache = cache
        self.log = log or (lambda _msg: None)

    # ------------------------------------------------------------------ 识别
    def identify(self, hashes: Sequence[str], progress: Callable[[int, int], None] | None = None,
                 ) -> dict[str, dict]:
        """sha1 -> version 对象（只包含 Modrinth 上存在的文件）。"""
        result: dict[str, dict] = {}
        pending: list[str] = []
        for sha1 in hashes:
            hit = self.cache.modrinth_versions.get(sha1)
            if hit:
                result[sha1] = hit
            else:
                pending.append(sha1)

        total = len(pending)
        done = 0
        for chunk in _chunks(pending, _BATCH):
            try:
                data = self.http.post_json(f"{BASE}/version_files",
                                           {"hashes": chunk, "algorithm": "sha1"})
            except Exception as exc:  # 网络异常不致命，剩余 jar 交给其他数据源
                self.log(f"Modrinth 批量识别失败：{exc}")
                break
            for sha1, version in (data or {}).items():
                result[sha1] = version
                self.cache.modrinth_versions.set(sha1, version)
            done += len(chunk)
            if progress:
                progress(min(done, total), total)
        return result

    # ------------------------------------------------------------------ 项目信息
    def projects(self, project_ids: Sequence[str]) -> dict[str, dict]:
        result: dict[str, dict] = {}
        pending: list[str] = []
        for pid in dict.fromkeys(project_ids):
            hit = self.cache.modrinth_projects.get(pid)
            if hit:
                result[pid] = hit
            else:
                pending.append(pid)
        for chunk in _chunks(pending, _PROJECT_BATCH):
            query = urllib.parse.quote(",".join(f'"{pid}"' for pid in chunk))
            try:
                data = self.http.get_json(f"{BASE}/projects?ids=[{query}]")
            except Exception as exc:
                self.log(f"Modrinth 项目信息获取失败：{exc}")
                continue
            for project in data or []:
                result[project["id"]] = project
                self.cache.modrinth_projects.set(project["id"], project)
        return result

    # ------------------------------------------------------------------ 最新版本
    def latest(self, hashes: Sequence[str], game_version: str, loader: str,
               progress: Callable[[int, int], None] | None = None) -> dict[str, dict]:
        """sha1 -> 该 MC 版本/加载器下最新的 version 对象。"""
        result: dict[str, dict] = {}
        total = len(hashes)
        done = 0
        for chunk in _chunks(list(hashes), _BATCH):
            payload = {
                "hashes": chunk,
                "algorithm": "sha1",
                "loaders": [loader] if loader else [],
                "game_versions": [game_version] if game_version else [],
            }
            try:
                data = self.http.post_json(f"{BASE}/version_files/update", payload)
                result.update(data or {})
            except Exception as exc:
                self.log(f"Modrinth 最新版本查询失败，改用逐项目查询：{exc}")
                result.update(self._latest_fallback(chunk, game_version, loader))
            done += len(chunk)
            if progress:
                progress(min(done, total), total)
        return result

    def _latest_fallback(self, hashes: Sequence[str], game_version: str,
                         loader: str) -> dict[str, dict]:
        versions = self.identify(hashes)
        result: dict[str, dict] = {}
        seen: set[str] = set()
        for sha1, version in versions.items():
            pid = version.get("project_id", "")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            listing = self.project_versions(pid, game_version, loader)
            if listing:
                result[sha1] = listing[0]
        return result

    def project_versions(self, project_id: str, game_version: str, loader: str) -> list[dict]:
        """按版本发布时间倒序返回项目版本列表（带缓存）。"""
        key = f"{project_id}|{game_version}|{loader}"
        cached = self.cache.modrinth_listings.get(key)
        if cached:
            return cached
        params = {}
        if game_version:
            params["game_versions"] = f'["{game_version}"]'
        if loader:
            params["loaders"] = f'["{loader}"]'
        try:
            data = self.http.get_json(f"{BASE}/project/{project_id}/version", params=params or None)
        except Exception as exc:
            self.log(f"Modrinth 版本列表获取失败（{project_id}）：{exc}")
            return []
        listing = data or []
        self.cache.modrinth_listings.set(key, listing)
        return listing
