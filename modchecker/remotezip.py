"""通过 HTTP Range 读取远端 zip 中的单个成员。

用途：官方整合包 zip 约 200 MB，但我们只需要里面的 ``manifest.json``
（几十 KB）。做法是先取尾部拿到中央目录，再按需取目标成员的数据块，
总共只需 2~3 个请求、几百 KB 流量。
"""

from __future__ import annotations

import struct
import zipfile
import zlib

from modchecker.net import HttpClient

_EOCD_SIG = b"PK\x05\x06"
_CD_SIG = b"PK\x01\x02"
_LOCAL_SIG = b"PK\x03\x04"

_TAIL_SIZES = (66_000, 300_000, 1_200_000)


class RemoteZipError(Exception):
    pass


class RemoteZip:
    def __init__(self, http: HttpClient, url: str) -> None:
        self.http = http
        self.url = url
        self._size = 0
        self._entries: dict[str, tuple[int, int, int, int]] | None = None  # name -> (method, csize, usize, lho)

    # ------------------------------------------------------------------ 内部
    def _load_directory(self) -> dict[str, tuple[int, int, int, int]]:
        if self._entries is not None:
            return self._entries
        self._size = self.http.content_length(self.url)
        if self._size <= 0:
            raise RemoteZipError("无法获取整合包体积")

        tail = b""
        eocd_pos = -1
        offset = 0
        for size in _TAIL_SIZES:
            size = min(size, self._size)
            tail = self.http.get_range(self.url, self._size - size, self._size - 1)
            eocd_pos = tail.rfind(_EOCD_SIG)
            if eocd_pos >= 0:
                offset = self._size - size
                break
        if eocd_pos < 0:
            raise RemoteZipError("未找到 zip 中央目录（可能不是标准 zip）")

        eocd = tail[eocd_pos:eocd_pos + 22]
        if len(eocd) < 22:
            raise RemoteZipError("zip 结构异常")
        _, _, _, _, total, cd_size, cd_off, _ = struct.unpack("<IHHHHIIH", eocd)
        if cd_off == 0xFFFFFFFF or total == 0xFFFF:
            raise RemoteZipError("不支持 ZIP64 整合包")

        cd_start_in_tail = cd_off - offset
        if cd_start_in_tail >= 0:
            directory = tail[cd_start_in_tail:cd_start_in_tail + cd_size]
        else:
            directory = self.http.get_range(self.url, cd_off, cd_off + cd_size - 1)

        entries: dict[str, tuple[int, int, int, int]] = {}
        cursor = 0
        while cursor + 46 <= len(directory) and directory[cursor:cursor + 4] == _CD_SIG:
            fields = struct.unpack("<IHHHHHHIIIHHHHHII", directory[cursor:cursor + 46])
            method, csize, usize, nlen, elen, clen, lho = (
                fields[4], fields[8], fields[9], fields[10], fields[11], fields[12], fields[16])
            raw_name = directory[cursor + 46:cursor + 46 + nlen]
            name = raw_name.decode("utf-8", "replace")
            entries[name] = (method, csize, usize, lho)
            cursor += 46 + nlen + elen + clen
        if not entries:
            raise RemoteZipError("中央目录解析失败")
        self._entries = entries
        return entries

    # ------------------------------------------------------------------ 公共
    def read(self, names: tuple[str, ...] | list[str]) -> bytes | None:
        """按顺序尝试读取第一个存在的成员。"""
        try:
            entries = self._load_directory()
        except RemoteZipError:
            raise
        except Exception as exc:  # 网络/解析异常统一上抛
            raise RemoteZipError(str(exc)) from exc

        lowered = {name.lower(): name for name in entries}
        for candidate in names:
            actual = entries.get(candidate) or entries.get(lowered.get(candidate.lower(), ""))
            if actual is None:
                continue
            method, csize, _usize, lho = actual
            header = self.http.get_range(self.url, lho, lho + 29)
            if header[:4] != _LOCAL_SIG:
                continue
            nlen, elen = struct.unpack("<HH", header[26:30])
            start = lho + 30 + nlen + elen
            if csize <= 0:
                continue
            payload = self.http.get_range(self.url, start, start + csize - 1)
            if method == 0:
                return payload
            if method == 8:
                return zlib.decompress(payload, -15)
            raise RemoteZipError(f"不支持的压缩方式 {method}")
        return None

    def read_json(self, names: tuple[str, ...] | list[str]):
        import json

        raw = self.read(names)
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8-sig", errors="replace"))
        except ValueError:
            return None


def is_zipfile(path: str) -> bool:
    return zipfile.is_zipfile(path)
