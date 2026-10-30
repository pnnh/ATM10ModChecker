"""CurseForge API 客户端。

CurseForge 官方 API 需要 API Key；因此默认使用社区的只读代理 ``api.curse.tools``
（请求/响应结构与官方一致）。若用户在设置里填入自己的 Key，则直连官方接口。

ATM10 的绝大多数模组是 CurseForge 独占或首发，Modrinth 只能覆盖约 60%，
所以这里承担：补全识别、最新版本查询、以及官方清单 projectID -> 文件名 的解析。
"""

from __future__ import annotations

import difflib
import re
from typing import Callable, Sequence

from modchecker.cache import CacheStore
from modchecker.i18n import t
from modchecker.models import JarEntry
from modchecker.net import HttpClient

PROXY_BASE = "https://api.curse.tools/v1/cf"
OFFICIAL_BASE = "https://api.curseforge.com/v1"

GAME_ID_MINECRAFT = 432
CLASS_ID_MODS = 6
MOD_LOADER_IDS = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
SHA1_ALGO = 1

Logger = Callable[[str], None]

_LOADER_SUFFIX_RE = re.compile(r"(?i)[\s_-]+(neoforge|forge|fabric|quilt|mc)$")
_BRACKET_RE = re.compile(r"\[[^\]]*\]")
_VERSION_CUT_RE = re.compile(r"(?<=[A-Za-z0-9)\]])(?:\s|_|-)+v?(?=\d)")
_EXT_RE = re.compile(r"(?i)\.jar(\.disabled)?$")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def file_sha1(data: dict) -> str:
    for entry in data.get("hashes") or []:
        if entry.get("algo") == SHA1_ALGO:
            return str(entry.get("value") or "").lower()
    return ""


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def humanize(text: str) -> str:
    """``AdvancedPeripherals`` -> ``Advanced Peripherals``。"""
    return re.sub(r"\s+", " ", _CAMEL_RE.sub(" ", text or "")).strip()


def search_terms(jar: JarEntry) -> list[str]:
    """由显示名 / modId / 文件名推导 CurseForge 搜索关键词。

    CurseForge 搜索是按“人类可读名称”做子串匹配的：``advancedperipherals``
    一条都搜不到，而 ``Advanced Peripherals`` 能命中。因此优先使用 jar 内
    ``fabric.mod.json`` / ``mods.toml`` 里的显示名，并把驼峰拆成空格。
    """
    terms: list[str] = []
    if jar.display_name:
        terms.append(jar.display_name)
        terms.append(humanize(jar.display_name))
    if jar.mod_id:
        terms.append(jar.mod_id.replace("_", " "))
        terms.append(humanize(jar.mod_id.replace("_", " ")))

    stem = _EXT_RE.sub("", jar.filename)
    stem = _BRACKET_RE.sub(" ", stem).strip()
    stem = _VERSION_CUT_RE.split(stem)[0]
    stem = _LOADER_SUFFIX_RE.sub("", stem.strip())
    stem = re.sub(r"[_-]+", " ", stem).strip()
    if stem:
        terms.append(stem)
        terms.append(humanize(stem))

    ordered: list[str] = []
    seen: set[str] = set()
    for term in terms:
        cleaned = re.sub(r"\s+", " ", term).strip()
        key = normalize(cleaned)
        if len(key) >= 3 and key not in seen:
            seen.add(key)
            ordered.append(cleaned)
    return ordered


def _loader_penalty(name: str, loader: str) -> float:
    lowered = (name or "").lower()
    if loader == "neoforge":
        if "fabric" in lowered or "quilt" in lowered:
            return 0.45
        if "forge" in lowered and "neoforge" not in lowered and "neo forge" not in lowered:
            return 0.2
    if loader == "fabric" and ("neoforge" in lowered or re.search(r"\bforge\b", lowered)):
        return 0.2
    return 0.0


def _score(candidate_name: str, term: str, loader: str) -> float:
    a = normalize(candidate_name)
    b = normalize(term)
    if not a or not b:
        return 0.0
    if a == b:
        base = 1.0
    elif a.startswith(b) or b.startswith(a):
        base = 0.9 * min(len(a), len(b)) / max(len(a), len(b)) + 0.1
    elif b in a:
        base = 0.85
    else:
        base = difflib.SequenceMatcher(None, a, b).ratio()
    return max(0.0, base - _loader_penalty(candidate_name, loader))


class CurseForgeProvider:
    def __init__(self, http: HttpClient, cache: CacheStore, api_key: str = "",
                 log: Logger | None = None) -> None:
        self.http = http
        self.cache = cache
        self.api_key = api_key.strip()
        self.log = log or (lambda _msg: None)

    @property
    def base(self) -> str:
        return OFFICIAL_BASE if self.api_key else PROXY_BASE

    @property
    def label(self) -> str:
        return t("provider.cf.official_api" if self.api_key else "provider.cf.proxy")

    # ------------------------------------------------------------------ 基础请求
    def _get(self, path: str, params: dict | None = None):
        headers = {"x-api-key": self.api_key} if self.api_key else None
        data = self.http.get_json(f"{self.base}{path}", params=params, headers=headers)
        return data

    def mod(self, mod_id: int | str) -> dict | None:
        key = str(mod_id)
        hit = self.cache.cf_mods.get(key)
        if hit:
            return hit
        try:
            data = self._get(f"/mods/{mod_id}")
        except Exception as exc:
            self.log(t("provider.cf.project_failed", id=mod_id, error=exc))
            return None
        mod = (data or {}).get("data")
        if isinstance(mod, dict):
            self.cache.cf_mods.set(key, mod)
            return mod
        return None

    def file(self, mod_id: int | str, file_id: int | str) -> dict | None:
        key = f"{mod_id}:{file_id}"
        hit = self.cache.cf_files.get(key)
        if hit:
            return hit
        try:
            data = self._get(f"/mods/{mod_id}/files/{file_id}")
        except Exception as exc:
            self.log(t("provider.cf.file_failed", id=mod_id, file=file_id, error=exc))
            return None
        file = (data or {}).get("data")
        if isinstance(file, dict):
            self.cache.cf_files.set(key, file)
            return file
        return None

    def listing(self, mod_id: int | str, game_version: str | None = None,
                loader: str | None = None, page_size: int = 50, index: int = 0,
                use_cache: bool = True) -> list[dict]:
        loader_id = MOD_LOADER_IDS.get(loader or "")
        key = f"{mod_id}|{game_version or ''}|{loader_id or ''}|{index}|{page_size}"
        if use_cache:
            hit = self.cache.cf_listings.get(key)
            if hit is not None:
                return hit
        params: dict[str, object] = {"pageSize": page_size, "index": index}
        if game_version:
            params["gameVersion"] = game_version
        if loader_id:
            params["modLoaderType"] = loader_id
        try:
            data = self._get(f"/mods/{mod_id}/files", params=params)
        except Exception as exc:
            self.log(t("provider.cf.files_failed", id=mod_id, error=exc))
            return []
        files = (data or {}).get("data") or []
        if use_cache:
            self.cache.cf_listings.set(key, files)
        return files

    def search(self, term: str, game_version: str | None = None, page_size: int = 12) -> list[dict]:
        key = f"{normalize(term)}|{game_version or ''}|{page_size}"
        hit = self.cache.cf_search.get(key)
        if hit is not None:
            return hit
        params: dict[str, object] = {
            "gameId": GAME_ID_MINECRAFT,
            "classId": CLASS_ID_MODS,
            "searchFilter": term,
            "sortField": 2,          # 按热度
            "sortOrder": "desc",
            "pageSize": page_size,
        }
        if game_version:
            params["gameVersion"] = game_version
        try:
            data = self._get("/mods/search", params=params)
        except Exception as exc:
            self.log(t("provider.cf.search_failed", term=term, error=exc))
            return []
        hits = (data or {}).get("data") or []
        self.cache.cf_search.set(key, hits)
        return hits

    # ------------------------------------------------------------------ 识别
    def resolve_jar(self, jar: JarEntry, game_version: str, loader: str
                    ) -> tuple[dict, dict | None, str]:
        """尝试把本地 jar 对应到 CurseForge 项目。

        返回 ``(项目, 精确文件或 None, 置信度说明)``；无法识别时返回 ``({}, None, "")``。
        """
        if jar.sha1:
            cached = self.cache.jar_identity.get(f"cf:{jar.sha1}")
            if cached is not None:
                if not cached.get("mod"):
                    return {}, None, ""
                return cached["mod"], cached.get("file"), cached.get("confidence", "")

        for term in search_terms(jar):
            for candidate, score in self._rank_candidates(term, game_version, loader):
                mod_id = candidate.get("id")
                if score >= 0.7:
                    hit = self._match_files(mod_id, jar, game_version, loader)
                    if hit is not None:
                        self._remember(jar, candidate, hit, "file")
                        return candidate, hit, "file"
                if score >= 0.9:
                    # 名称几乎完全一致，但文件不在最近的文件列表中：退化为按项目关联
                    self._remember(jar, candidate, None, "name")
                    return candidate, None, "name"
        if jar.sha1:
            self.cache.jar_identity.set(f"cf:{jar.sha1}", {"mod": None})
        return {}, None, ""

    def _rank_candidates(self, term: str, game_version: str, loader: str,
                         limit: int = 3) -> list[tuple[dict, float]]:
        """搜索并按名称相似度排序；带版本过滤搜不到时退回不带过滤的搜索。"""
        for version_filter in (game_version, None):
            ranked = [(hit, _score(hit.get("name", ""), term, loader))
                      for hit in self.search(term, version_filter)]
            ranked = [(hit, score) for hit, score in ranked if score >= 0.5]
            if ranked:
                ranked.sort(key=lambda item: item[1], reverse=True)
                return ranked[:limit]
        return []

    def _match_files(self, mod_id: int, jar: JarEntry, game_version: str,
                     loader: str) -> dict | None:
        target_name = jar.filename.lower()
        for game, load in ((game_version, loader), (None, None)):
            files = self.listing(mod_id, game, load, page_size=50, index=0)
            for item in files:
                if jar.sha1 and file_sha1(item) == jar.sha1:
                    return item
            for item in files:
                if str(item.get("fileName", "")).lower() == target_name:
                    return item
        return None

    def _remember(self, jar: JarEntry, mod: dict, file: dict | None, confidence: str) -> None:
        if jar.sha1:
            self.cache.jar_identity.set(f"cf:{jar.sha1}",
                                        {"mod": mod, "file": file, "confidence": confidence})

    # ------------------------------------------------------------------ 最新版本
    def latest_file(self, mod_id: int | str, game_version: str, loader: str,
                    allow_prerelease: bool = False) -> dict | None:
        """该 MC 版本/加载器下最新的文件。

        默认只返回正式版：稳定通道的模组要跳过 beta/alpha。``allow_prerelease``
        供本地本身就走预发布通道的模组使用。
        """
        files = self.listing(mod_id, game_version, loader, page_size=30, index=0)
        if not files:
            return None
        if allow_prerelease:
            return files[0]
        for item in files:
            if item.get("releaseType") == 1:  # 1 = Release
                return item
        return None
