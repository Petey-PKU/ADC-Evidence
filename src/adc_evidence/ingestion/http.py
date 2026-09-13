from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


USER_AGENT = "ADC-Evidence/0.2 (educational research project)"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def fetch_bytes(
    url: str,
    *,
    timeout: int = 30,
    retries: int = 2,
    extra_headers: dict[str, str] | None = None,
    data: bytes | None = None,
) -> bytes:
    """Fetch bytes with bounded retries.

    Passing ``data`` sends a POST request.  This is needed for registry
    endpoints such as PubMed ESearch when a transparent query becomes too
    long for a proxy or server URL limit.
    """
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    headers.update(extra_headers or {})
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(url, data=data, headers=headers)
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last_error}") from last_error


def write_snapshot(path: Path, content: bytes) -> tuple[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return str(path), sha256_bytes(content)


def write_json(path: Path, payload: object) -> tuple[str, str]:
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return write_snapshot(path, content)
