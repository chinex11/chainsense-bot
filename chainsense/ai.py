"""Optional: Claude writes the narrative, video angles and lesson from the collected data.

Only runs when ANTHROPIC_API_KEY is set. Without it the brief still sends, just without
the analyst commentary section.
"""
from __future__ import annotations

import json
import os

from .http import post_json

SYSTEM = """You are the research analyst for Chainsense, a YouTube channel about crypto news,
market updates, and helping people get better at crypto. You receive today's raw data
(market, sentiment, DeFi, stablecoins, Bitcoin network, on-chain watchlist events, headlines).

Rules:
- Use ONLY the numbers in the data. Never invent prices, flows, or events.
- Headlines are reports, not verified facts; say "reported" where it matters.
- Neutral, clear, no hype, no buy/sell calls. This is content research, not financial advice.

Return plain text with exactly these sections (Telegram-friendly, short lines, no markdown tables):
WHAT MATTERED TODAY: 3-5 bullets connecting the data to the headlines.
MARKET READ: 2-3 sentences on sentiment and positioning implied by the data.
VIDEO ANGLES: 3 ideas, each as "Title — hook — who it helps (beginner/experienced)".
LESSON OF THE DAY: one practical tip tied to something in today's data."""


def analyst_notes(data: dict, cfg: dict) -> str | None:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    model = (cfg.get("ai") or {}).get("model", "claude-sonnet-5")
    payload = {
        "model": model,
        "max_tokens": 1200,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": "Today's data:\n" + json.dumps(data, default=str)[:60000]}],
    }
    r = post_json("https://api.anthropic.com/v1/messages", payload,
                  headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                           "content-type": "application/json"}, timeout=90)
    return "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text").strip() or None
