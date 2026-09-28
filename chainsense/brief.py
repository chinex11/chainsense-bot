"""Daily brief: collect everything, compare with yesterday, format for Telegram."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from . import onchain, sources
from .ai import analyst_notes
from .core import State, esc

LAGOS = timezone(timedelta(hours=1))


def usd(x: float | None) -> str:
    if x is None:
        return "n/a"
    if abs(x) < 0.005:
        return "$0"
    a = abs(x)
    sign = "-" if x < 0 else ""
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{sign}${a / div:.2f}{suf}"
    return f"{sign}${a:,.2f}" if a >= 1 else f"{sign}${a:.6f}".rstrip("0")


def price(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"${x:,.2f}" if x >= 1 else f"${x:.6f}".rstrip("0")


def pct(x: float | None) -> str:
    if x is None:
        return "n/a"
    arrow = "🟢" if x > 0 else "🔴" if x < 0 else "⚪"
    return f"{arrow} {x:+.2f}%"


def collect(cfg: dict, state: State) -> tuple[dict, list[str]]:
    wl = cfg["watchlist"]
    errors: list[str] = []
    d: dict = {}

    def run(name, fn, *a, **kw):
        res, err = sources.safe(fn, *a, **kw)
        if err:
            errors.append(err)
        d[name] = res

    run("global", sources.market_global)
    ids = list(dict.fromkeys((cfg.get("majors") or []) + [t["coingecko_id"] for t in wl["tokens"]]))
    run("markets", sources.top_markets, 100, ids)
    run("trending", sources.trending)
    run("fear_greed", sources.fear_greed)
    run("tvl", sources.chain_tvl, cfg.get("tvl_chains") or ["Ethereum", "Solana", "Base", "BSC", "Tron", "Arbitrum"])
    run("stables", sources.stablecoins)
    run("btc_net", sources.btc_network)
    run("news", sources.news, cfg.get("news_feeds") or {}, 24)
    if d["markets"]:
        d["movers"] = sources.movers(d["markets"])

    # TVL change vs the previous daily run
    prev_tvl = state.get("tvl", {})
    for r in d["tvl"] or []:
        old = prev_tvl.get(r["chain"])
        r["chg_pct"] = (r["tvl"] / old - 1) * 100 if old else None
    if d["tvl"]:
        state.set("tvl", {r["chain"]: r["tvl"] for r in d["tvl"]})

    # Wallet activity in the last 24h
    since = time.time() - 86400
    d["wallets"] = []
    for w in wl["wallets"]:
        res, err = sources.safe(onchain.wallet, w["chain"], w["address"])
        if err:
            errors.append(f"wallet {w.get('label', w['address'][:8])}: {err}")
            continue
        res["label"] = w.get("label") or w["address"][:6] + "…" + w["address"][-4:]
        res["events_24h"] = [e for e in res["events"] if (e.get("ts") or time.time()) >= since]
        d["wallets"].append(res)

    # Whale transfers for watched token contracts
    d["whales"] = []
    for t in wl["token_whales"]:
        res, err = sources.safe(onchain.evm_token_whales, t["chain"], t["contract"], t["min_amount"])
        if err:
            errors.append(f"whales {t.get('label')}: {err}")
            continue
        d["whales"] += [dict(x, label=t.get("label")) for x in res if (x["ts"] or 0) >= since][:5]
    return d, errors


def format_brief(d: dict, errors: list[str], cfg: dict, notes: str | None) -> str:
    now = datetime.now(LAGOS)
    L = [f"<b>📊 CHAINSENSE DAILY BRIEF</b>\n{now:%A, %d %b %Y} · {now:%H:%M} Lagos"]

    g = d.get("global")
    if g:
        L.append("<b>🌍 Market</b>\n"
                 f"Total cap: {usd(g['total_mcap_usd'])} ({pct(g['mcap_change_24h_pct'])})\n"
                 f"24h volume: {usd(g['total_volume_usd'])}\n"
                 f"BTC dom: {g['btc_dominance']:.1f}% · ETH dom: {g['eth_dominance']:.1f}%")

    fg = d.get("fear_greed")
    if fg:
        L.append(f"<b>😨 Fear & Greed:</b> {fg['value']} ({esc(fg['label'])}) · "
                 f"yesterday {fg['yesterday']} · week ago {fg['week_ago']}")

    mk = {m["id"]: m for m in d.get("markets") or []}
    majors = [mk[i] for i in cfg.get("majors") or [] if i in mk]
    if majors:
        rows = [f"<code>{m['symbol']:<5}</code> {price(m['price'])}  24h {pct(m['chg_24h'])}  7d {m['chg_7d'] or 0:+.1f}%"
                for m in majors]
        L.append("<b>💰 Majors</b>\n" + "\n".join(rows))

    mv = d.get("movers")
    if mv:
        up = "\n".join(f"  {m['symbol']} {m['chg_24h']:+.1f}% ({price(m['price'])})" for m in mv["gainers"])
        dn = "\n".join(f"  {m['symbol']} {m['chg_24h']:+.1f}% ({price(m['price'])})" for m in mv["losers"])
        L.append(f"<b>🚀 Top-100 gainers</b>\n{up}\n<b>📉 Top-100 losers</b>\n{dn}")

    tr = d.get("trending")
    if tr:
        L.append("<b>🔥 Trending searches</b>\n" + ", ".join(f"{esc(t['name'])} ({esc(t['symbol'])})" for t in tr[:8]))

    st = d.get("stables")
    if st:
        top = "\n".join(f"  {esc(a['symbol'])}: {usd(a['supply'])} (1d {usd(a['chg_1d'])}, 7d {usd(a['chg_7d'])})"
                        for a in st["top"][:4])
        dep = ""
        if st["depegs"]:
            dep = "\n⚠️ Off-peg: " + ", ".join(f"{esc(a['symbol'])} ${a['price']:.3f}" for a in st["depegs"])
        L.append(f"<b>💵 Stablecoins</b>\nTotal: {usd(st['total'])} · 1d {usd(st['chg_1d'])} · 7d {usd(st['chg_7d'])}\n{top}{dep}")

    tvl = d.get("tvl")
    if tvl:
        L.append("<b>🏦 DeFi TVL by chain</b>\n" + "\n".join(
            f"  {esc(r['chain'])}: {usd(r['tvl'])}" + (f" ({r['chg_pct']:+.1f}% vs yesterday)" if r.get("chg_pct") is not None else "")
            for r in tvl))

    bn = d.get("btc_net")
    if bn:
        L.append(f"<b>⛓ Bitcoin network</b>\nFees: {bn['fee_fast']} sat/vB fast · {bn['fee_hour']} 1h · "
                 f"hashrate ~{bn['hashrate_ehs']:.0f} EH/s")

    # Watchlist tokens
    wl_tokens = [(t, mk.get(t["coingecko_id"])) for t in cfg["watchlist"]["tokens"]]
    wl_tokens = [(t, m) for t, m in wl_tokens if m]
    if wl_tokens:
        L.append("<b>👀 Your watchlist</b>\n" + "\n".join(
            f"  {esc(t.get('label') or m['symbol'])}: {price(m['price'])} 24h {pct(m['chg_24h'])}" for t, m in wl_tokens))

    for w in d.get("wallets") or []:
        head = f"<b>🔎 {esc(w['label'])}</b> ({w['chain']}) · balance {w['balance']:,.4f} {w['native']}"
        if not w["events_24h"]:
            L.append(head + "\n  No movements in 24h ✅")
        else:
            L.append(head + "\n" + "\n".join(_event_line(e) for e in w["events_24h"][:8]))

    if d.get("whales"):
        L.append("<b>🐋 Large transfers (verified on-chain)</b>\n" + "\n".join(
            f"  {x['amount']:,.0f} {esc(x['symbol'])} {esc(x['from_label'] or _short(x['from']))} → "
            f"{esc(x['to_label'] or _short(x['to']))} · <a href=\"{x['url']}\">tx</a>" for x in d["whales"][:8]))

    if notes:
        L.append("<b>🧠 Analyst notes</b>\n" + esc(notes))

    nw = d.get("news") or []
    if nw:
        L.append("<b>📰 Headlines (reported)</b>\n" + "\n".join(
            f"• <a href=\"{esc(n['link'])}\">{esc(n['title'])}</a> — {esc(n['source'])}" for n in nw[:12]))

    if errors:
        L.append("<i>Sources that failed this run: " + esc("; ".join(e.split(":")[0] for e in errors)) + "</i>")
    L.append("<i>For research and content only — not financial advice.</i>")
    return "\n\n".join(L)


def _short(a: str | None) -> str:
    return (a[:6] + "…" + a[-4:]) if a and len(a) > 12 else (a or "?")


def _event_line(e: dict) -> str:
    arrow = "⬇️ in " if e["direction"] == "in" else "⬆️ out"
    cp = f" {'from' if e['direction'] == 'in' else 'to'} {_short(e['counterparty'])}" if e.get("counterparty") else ""
    link = f" · <a href=\"{e['url']}\">tx</a>" if e.get("url") else ""
    return f"  {arrow} {e['amount']:,.4f} {esc(e['symbol'])}{cp}{link}"


def run_daily(cfg: dict, state: State, dry_run: bool = False) -> str:
    from .core import send

    data, errors = collect(cfg, state)
    notes = None
    try:
        notes = analyst_notes({k: v for k, v in data.items() if k != "markets"} |
                              {"majors": [m for m in data.get("markets") or [] if m["id"] in (cfg.get("majors") or [])]},
                              cfg)
    except Exception as e:  # noqa: BLE001
        errors.append(f"analyst_notes: {e}")
    text = format_brief(data, errors, cfg, notes)
    send(text, dry_run=dry_run)
    state.save()
    return text
