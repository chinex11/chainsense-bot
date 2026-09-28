"""Watch mode: run every 10–15 minutes, alert only on NEW things.

- New transactions on watched wallets (above per-wallet min_amount)
- Watched tokens moving more than alert_pct since the last alert
- Whale transfers of watched token contracts
The first run only records what already exists, so you don't get flooded.
"""
from __future__ import annotations

from . import onchain, sources
from .brief import _event_line, _short, pct, price
from .core import State, esc, send

MAX_SEEN = 400


def run_watch(cfg: dict, state: State, dry_run: bool = False) -> list[str]:
    wl = cfg["watchlist"]
    th = cfg.get("alerts") or {}
    first_run = not state.get("watch_initialised")
    seen: list[str] = state.get("seen", [])
    seen_set = set(seen)
    alerts: list[str] = []

    # 1) Wallet movements
    for w in wl["wallets"]:
        res, err = sources.safe(onchain.wallet, w["chain"], w["address"])
        if err:
            continue
        label = w.get("label") or _short(w["address"])
        new = [e for e in res["events"] if e["id"] not in seen_set
               and e["amount"] >= float(w.get("min_amount", 0))]
        for e in res["events"]:
            if e["id"] not in seen_set:
                seen.append(e["id"]); seen_set.add(e["id"])
        if new and not first_run:
            alerts.append(f"<b>🔔 {esc(label)}</b> ({w['chain']}) moved\n" +
                          "\n".join(_event_line(e) for e in new[:6]) +
                          f"\nBalance now: {res['balance']:,.4f} {res['native']}")

    # 2) Price moves on watched tokens
    ids = [t["coingecko_id"] for t in wl["tokens"]]
    if ids:
        rows, err = sources.safe(sources.top_markets, 1, ids)
        last = state.get("alert_prices", {})
        pct_th = float(th.get("price_move_pct", 5))
        for m in rows or []:
            if m["id"] not in ids:
                continue
            ref = last.get(m["id"])
            if ref is None:
                last[m["id"]] = m["price"]
                continue
            move = (m["price"] / ref - 1) * 100
            if abs(move) >= pct_th:
                label = next((t.get("label") for t in wl["tokens"] if t["coingecko_id"] == m["id"]), None) or m["symbol"]
                alerts.append(f"<b>{'📈' if move > 0 else '📉'} {esc(label)}</b> {move:+.1f}% since last alert → "
                              f"{price(m['price'])} (24h {pct(m['chg_24h'])})")
                last[m["id"]] = m["price"]
        state.set("alert_prices", last)

    # 3) Whale transfers
    for t in wl["token_whales"]:
        res, err = sources.safe(onchain.evm_token_whales, t["chain"], t["contract"], t["min_amount"])
        if err:
            continue
        new = [x for x in res if x["id"] not in seen_set]
        for x in new:
            seen.append(x["id"]); seen_set.add(x["id"])
        if new and not first_run:
            alerts.append(f"<b>🐋 {esc(t.get('label') or 'Whale')}</b>\n" + "\n".join(
                f"  {x['amount']:,.0f} {esc(x['symbol'])} {esc(x['from_label'] or _short(x['from']))} → "
                f"{esc(x['to_label'] or _short(x['to']))} · <a href=\"{x['url']}\">verify</a>" for x in new[:5]))

    state.set("seen", seen[-MAX_SEEN:])
    state.set("watch_initialised", True)
    state.save()
    if alerts:
        send("\n\n".join(alerts), dry_run=dry_run)
    elif first_run:
        send("✅ Chainsense watch mode is live. I'll alert you on new wallet moves, "
             "big price swings and whale transfers.", dry_run=dry_run)
    return alerts
