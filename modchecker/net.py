"""轻量 HTTP 客户端：限速、重试、Range 请求。仅使用标准库。"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from modchecker.i18n import t

USER_AGENT = "ATM10-ModChecker/1.0 (open-source desktop tool)"


class HttpError(Exception):
    """HTTP 层错误（含状态码与响应片段，便于界面展示）。"""

    def __init__(self, status: int, url: str, body: str = "") -> None:
        self.status = status
        self.url = url
        self.body = body
        super().__init__(f"HTTP {status} - {url} {body[:180]}".strip())


class Cancelled(Exception):
    """用户主动取消。"""


class HttpClient:
    """线程安全的简单客户端。

    ``rate_per_sec`` 对全局请求做粗略限速，避免触发 Modrinth/CurseForge 的
    速率限制（Modrinth 为 300 次/分钟）。
    """

    def __init__(
        self,
        timeout: float = 30.0,
        retries: int = 3,
        rate_per_sec: float = 8.0,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self._min_interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
        self._lock = threading.Lock()
        self._next_at = 0.0
        self._cancel = cancel_event or threading.Event()

    # ------------------------------------------------------------------ 公共接口
    def get_json(self, url: str, params: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None) -> Any:
        return self._decode(self.request("GET", url, params=params, headers=headers), url)

    def post_json(self, url: str, payload: Any, headers: dict[str, str] | None = None) -> Any:
        merged = {"Content-Type": "application/json"}
        merged.update(headers or {})
        body = json.dumps(payload).encode("utf-8")
        return self._decode(self.request("POST", url, data=body, headers=merged), url)

    def get_range(self, url: str, start: int, end: int) -> bytes:
        headers = {"Range": f"bytes={start}-{end}"}
        return self.request("GET", url, headers=headers, expect_partial=True)

    def content_length(self, url: str) -> int:
        req = self._build("HEAD", url, None, None)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return int(resp.headers.get("Content-Length") or 0)

    # ------------------------------------------------------------------ 内部实现
    @staticmethod
    def _decode(raw: bytes, url: str) -> Any:
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError as exc:  # 非 JSON 响应
            raise HttpError(0, url, f"响应不是合法 JSON: {raw[:120]!r}") from exc

    def _build(self, method: str, url: str, data: bytes | None,
               headers: dict[str, str] | None) -> urllib.request.Request:
        merged = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        merged.update(headers or {})
        return urllib.request.Request(url, data=data, headers=merged, method=method)

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._next_at = now + self._min_interval

    def request(self, method: str, url: str, params: dict[str, Any] | None = None,
                data: bytes | None = None, headers: dict[str, str] | None = None,
                expect_partial: bool = False) -> bytes:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            if self._cancel.is_set():
                raise Cancelled()
            self._throttle()
            try:
                req = self._build(method, url, data, headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")
                except Exception:  # pragma: no cover - 读取失败不影响主流程
                    pass
                # 4xx（除 429）不重试
                if exc.code != 429 and 400 <= exc.code < 500:
                    raise HttpError(exc.code, url, body) from exc
                last_exc = HttpError(exc.code, url, body)
                self._sleep_backoff(attempt, exc.headers.get("Retry-After"))
            except urllib.error.URLError as exc:
                last_exc = HttpError(0, url, str(exc.reason))
                self._sleep_backoff(attempt)
            except TimeoutError as exc:
                last_exc = HttpError(0, url, t("net.timeout"))
                self._sleep_backoff(attempt)
        assert last_exc is not None
        raise last_exc

    def _sleep_backoff(self, attempt: int, retry_after: str | None = None) -> None:
        if attempt >= self.retries:
            return
        delay = min(2.0 * (attempt + 1), 8.0)
        if retry_after:
            try:
                delay = max(delay, min(float(retry_after), 15.0))
            except ValueError:
                pass
        time.sleep(delay)
