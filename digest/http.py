"""Minimal HTTP helper built on the standard library (no third-party deps)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

USER_AGENT = "southborough-meeting-digest/1.0 (+https://github.com)"


class HTTPError(Exception):
    def __init__(self, status: int, message: str, body: str = ""):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message
        self.body = body


def request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any = None,
    timeout: float = 60,
    retries: int = 3,
    sleep=time.sleep,
) -> bytes:
    """Send a request, retrying network errors and 5xx responses with backoff.

    4xx responses are raised immediately as HTTPError (the caller decides).
    """
    data = None
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            msg = _error_message(text) or e.reason
            if e.code < 500 or attempt == retries:
                raise HTTPError(e.code, str(msg), text) from None
            last_exc = HTTPError(e.code, str(msg), text)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_exc = e
            if attempt == retries:
                raise
        sleep(min(60, 5 * 2**attempt))
    raise last_exc  # pragma: no cover


def get_json(url: str, **kw) -> Any:
    return json.loads(request("GET", url, **kw))


def _error_message(text: str) -> str:
    try:
        payload = json.loads(text)
    except ValueError:
        return text[:300]
    err = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(err, dict):
        return err.get("message") or err.get("status") or text[:300]
    return text[:300]
