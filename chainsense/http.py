"""Small HTTP helpers with retries and polite timeouts."""
from __future__ import annotations

import time
from typing import Any

import requests

USER_AGENT = "ChainsenseBot/1.0 (+https://youtube.com/@chainsense)"
_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})


class FetchError(RuntimeError):
    pass


def get_json(url: str, params: dict | None = None, headers: dict | None = None,
             retries: int = 3, timeout: int = 20) -> Any:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = _session.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 429:  # rate limited: back off and retry
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise FetchError(f"GET {url} failed: {last}")


def post_json(url: str, payload: dict, headers: dict | None = None,
              retries: int = 3, timeout: int = 30) -> Any:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = _session.post(url, json=payload, headers=headers, timeout=timeout)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            if 400 <= r.status_code < 500:  # client errors won't fix themselves; show the reason
                raise FetchError(f"POST {url.split('/bot')[0]}… returned {r.status_code}: {r.text[:300]}")
            r.raise_for_status()
            return r.json()
        except FetchError:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise FetchError(f"POST {url.split('/bot')[0]} failed: {last}")


def get_text(url: str, timeout: int = 20) -> str:
    r = _session.get(url, timeout=timeout, headers={"Accept": "*/*"})
    r.raise_for_status()
    return r.text
