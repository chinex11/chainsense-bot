"""Market, sentiment, DeFi, Bitcoin-network and news collectors.

All sources are free/public. A CoinGecko demo key is optional but raises rate limits.
Every function returns plain dicts so the brief and the AI summary can use them.
"""
from __future__ import annotations

import calendar
import os
import time
from typing import Any

from .http import FetchError, get_json

CG = "https://api.coingecko.com/api/v3"


def _cg_headers() -> dict:
    key = os.getenv("COINGECKO_API_KEY")
    return {"x-cg-demo-api-key": key} if key else {}


# ---------------------------------------------------------------- market
def market_global() -> dict:
    d = get_json(f"{CG}/global", headers=_cg_headers())["data"]
    return {
        "total_mcap_usd": d["total_market_cap"]["usd"],
        "total_volume_usd": d["total_volume"]["usd"],
        "mcap_change_24h_pct": d.get("market_cap_change_percentage_24h_usd"),
        "btc_dominance": d["market_cap_percentage"].get("btc"),
        "eth_dominance": d["market_cap_percentage"].get("eth"),
    }


def top_markets(n: int = 100, extra_ids: list[str] | None = None) -> list[dict]:
    """Top-n coins by market cap, plus any watchlist ids outside the top n."""
    params = {"vs_currency": "usd", "order": "market_cap_desc", "per_page": n, "page": 1,
              "price_change_percentage": "24h,7d"}
    rows = get_json(f"{CG}/coins/markets", params=params, headers=_cg_headers())
    have = {r["id"] for r in rows}
    missing = [i for i in (extra_ids or []) if i not in have]
    if missing:
        params = {"vs_currency": "usd", "ids": ",".join(missing), "price_change_percentage": "24h,7d"}
        rows += get_json(f"{CG}/coins/markets", params=params, headers=_cg_headers())
    return [{
        "id": r["id"], "symbol": r["symbol"].upper(), "name": r["name"],
        "price": r["current_price"], "mcap": r.get("market_cap"), "rank": r.get("market_cap_rank"),
        "vol_24h": r.get("total_volume"),
        "chg_24h": r.get("price_change_percentage_24h_in_currency"),
        "chg_7d": r.get("price_change_percentage_7d_in_currency"),
    } for r in rows]


def movers(markets: list[dict], k: int = 5, top_n: int = 100) -> dict:
    pool = [m for m in markets if m["rank"] and m["rank"] <= top_n and m["chg_24h"] is not None
            and m["symbol"] not in STABLE_SYMBOLS]
    pool.sort(key=lambda m: m["chg_24h"], reverse=True)
    return {"gainers": pool[:k], "losers": list(reversed(pool[-k:]))}


STABLE_SYMBOLS = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "PYUSD", "USDS", "USD1", "USDD", "BUSD"}


def trending() -> list[dict]:
    d = get_json(f"{CG}/search/trending", headers=_cg_headers())
    return [{"name": c["item"]["name"], "symbol": c["item"]["symbol"].upper(),
             "rank": c["item"].get("market_cap_rank")} for c in d.get("coins", [])[:10]]


def fear_greed() -> dict:
    d = get_json("https://api.alternative.me/fng/", params={"limit": 8})["data"]
    today, yday, week = d[0], d[1], d[min(7, len(d) - 1)]
    return {"value": int(today["value"]), "label": today["value_classification"],
            "yesterday": int(yday["value"]), "week_ago": int(week["value"])}


# ---------------------------------------------------------------- defi
def chain_tvl(chains: list[str]) -> list[dict]:
    rows = get_json("https://api.llama.fi/v2/chains")
    want = {c.lower() for c in chains}
    out = [{"chain": r["name"], "tvl": r.get("tvl") or 0} for r in rows if r["name"].lower() in want]
    out.sort(key=lambda r: r["tvl"], reverse=True)
    return out


def stablecoins(top: int = 6) -> dict:
    d = get_json("https://stablecoins.llama.fi/stablecoins", params={"includePrices": "true"})
    assets = []
    total = total_prev_day = total_prev_week = 0.0
    for a in d["peggedAssets"]:
        if a.get("pegType") != "peggedUSD":
            continue
        now = (a.get("circulating") or {}).get("peggedUSD") or 0
        pd_ = (a.get("circulatingPrevDay") or {}).get("peggedUSD") or 0
        pw = (a.get("circulatingPrevWeek") or {}).get("peggedUSD") or 0
        total += now; total_prev_day += pd_; total_prev_week += pw
        assets.append({"symbol": a["symbol"], "supply": now, "chg_1d": now - pd_, "chg_7d": now - pw,
                       "price": a.get("price")})
    assets.sort(key=lambda a: a["supply"], reverse=True)
    depegs = [a for a in assets[:25] if a["price"] and abs(a["price"] - 1) > 0.01]
    return {"total": total, "chg_1d": total - total_prev_day, "chg_7d": total - total_prev_week,
            "top": assets[:top], "depegs": depegs}


# ---------------------------------------------------------------- bitcoin network
def btc_network() -> dict:
    fees = get_json("https://mempool.space/api/v1/fees/recommended")
    hr = get_json("https://mempool.space/api/v1/mining/hashrate/3d")
    return {"fee_fast": fees["fastestFee"], "fee_hour": fees["hourFee"], "fee_min": fees["minimumFee"],
            "hashrate_ehs": (hr.get("currentHashrate") or 0) / 1e18,
            "difficulty": hr.get("currentDifficulty")}


# ---------------------------------------------------------------- news
def news(feeds: dict[str, str], hours: int = 24, per_feed: int = 6) -> list[dict]:
    import feedparser  # local import: optional dependency for tests

    cutoff = time.time() - hours * 3600
    items: list[dict] = []
    for source, url in feeds.items():
        try:
            parsed = feedparser.parse(url, agent="ChainsenseBot/1.0")
        except Exception:  # noqa: BLE001
            continue
        count = 0
        for e in parsed.entries:
            t = e.get("published_parsed") or e.get("updated_parsed")
            ts = calendar.timegm(t) if t else None
            if ts and ts < cutoff:
                continue
            items.append({"source": source, "title": e.get("title", "").strip(),
                          "link": e.get("link"), "ts": ts})
            count += 1
            if count >= per_feed:
                break
    items.sort(key=lambda i: i["ts"] or 0, reverse=True)
    return _dedupe(items)


def _dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for i in items:
        key = "".join(ch for ch in i["title"].lower() if ch.isalnum())[:60]
        if key and key not in seen:
            seen.add(key); out.append(i)
    return out


def safe(fn, *a, **kw) -> tuple[Any, str | None]:
    """Run a collector; return (result, error) so one dead API never kills the brief."""
    try:
        return fn(*a, **kw), None
    except (FetchError, KeyError, ValueError, TypeError, IndexError) as e:
        return None, f"{fn.__name__}: {e}"
