"""Config, state and delivery (Telegram / console)."""
from __future__ import annotations

import html
import json
import os
from pathlib import Path

import yaml

from .http import post_json

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | None = None) -> dict:
    p = Path(path or os.getenv("CHAINSENSE_CONFIG") or ROOT / "config.yaml")
    if not p.exists():
        p = ROOT / "config.example.yaml"
    cfg = yaml.safe_load(p.read_text()) or {}
    cfg.setdefault("watchlist", {})
    for k in ("tokens", "wallets", "token_whales"):
        cfg["watchlist"][k] = cfg["watchlist"].get(k) or []
    return cfg


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.split(" #", 1)[0].strip()
                if v.startswith("#"):
                    v = ""
                if v:
                    os.environ.setdefault(k.strip(), v.strip('"').strip("'"))


_load_dotenv()


class State:
    """Tiny JSON store: seen tx ids, last alert prices, yesterday's TVL."""

    def __init__(self, path: str | None = None):
        self.path = Path(path or os.getenv("CHAINSENSE_STATE") or ROOT / "state" / "state.json")
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        tmp.replace(self.path)


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def send(text_html: str, dry_run: bool = False) -> None:
    """Send Telegram HTML, split under the 4096-char limit. Falls back to printing."""
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if dry_run or not (token and chat):
        if not dry_run:
            print("[notify] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — printing instead.\n")
        print(text_html)
        return
    for chunk in _split(text_html, 3900):
        post_json(f"https://api.telegram.org/bot{token}/sendMessage",
                  {"chat_id": chat, "text": chunk, "parse_mode": "HTML",
                   "disable_web_page_preview": True})


def _split(text: str, limit: int) -> list[str]:
    parts, cur = [], ""
    for block in text.split("\n\n"):
        if len(cur) + len(block) + 2 > limit and cur:
            parts.append(cur); cur = ""
        while len(block) > limit:  # a single giant block: cut on newlines
            cut = block.rfind("\n", 0, limit)
            cut = cut if cut > 0 else limit
            parts.append(block[:cut]); block = block[cut:].lstrip("\n")
        cur = f"{cur}\n\n{block}" if cur else block
    if cur:
        parts.append(cur)
    return parts
