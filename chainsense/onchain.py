"""On-chain reads: wallet balances, new transactions, whale token transfers, tx verification.

EVM chains use Blockscout's free v2 API (no key). Bitcoin uses mempool.space.
Solana uses JSON-RPC (public endpoint by default; set SOLANA_RPC_URL for a Helius/QuickNode URL).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from .http import get_json, post_json

BLOCKSCOUT = {
    "eth": ("https://eth.blockscout.com", "ETH", "https://eth.blockscout.com/tx/"),
    "base": ("https://base.blockscout.com", "ETH", "https://base.blockscout.com/tx/"),
    "arbitrum": ("https://arbitrum.blockscout.com", "ETH", "https://arbitrum.blockscout.com/tx/"),
    "optimism": ("https://optimism.blockscout.com", "ETH", "https://optimism.blockscout.com/tx/"),
    "polygon": ("https://polygon.blockscout.com", "POL", "https://polygon.blockscout.com/tx/"),
    "gnosis": ("https://gnosis.blockscout.com", "xDAI", "https://gnosis.blockscout.com/tx/"),
}
MEMPOOL = "https://mempool.space/api"


def _sol_rpc() -> str:
    return os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")


def _iso(ts: str | None) -> float | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def _h(obj) -> str | None:
    return obj.get("hash") if isinstance(obj, dict) else obj


# ---------------------------------------------------------------- EVM
def evm_wallet(chain: str, address: str, limit: int = 15) -> dict:
    base, native, explorer = BLOCKSCOUT[chain]
    info = get_json(f"{base}/api/v2/addresses/{address}")
    bal = int(info.get("coin_balance") or 0) / 1e18
    txs = get_json(f"{base}/api/v2/addresses/{address}/transactions").get("items", [])[:limit]
    tts = get_json(f"{base}/api/v2/addresses/{address}/token-transfers").get("items", [])[:limit]
    events = []
    for t in txs:
        val = int(t.get("value") or 0) / 1e18
        if val == 0:
            continue  # contract calls with no native value show up as token transfers instead
        events.append(_evm_event(address, t["hash"], _h(t.get("from")), _h(t.get("to")), val, native,
                                 t.get("timestamp"), explorer))
    for t in tts:
        total = t.get("total") or {}
        if "value" not in total or t.get("token_type") in ("ERC-721", "ERC-1155", "ERC-404"):
            continue  # skip NFTs; this watches fungible token movements
        dec = int(total.get("decimals") or (t.get("token") or {}).get("decimals") or 18)
        try:
            val = int(total.get("value") or 0) / 10 ** dec
        except (TypeError, ValueError):
            continue
        if val == 0:
            continue
        sym = (t.get("token") or {}).get("symbol") or "TOKEN"
        h = t.get("transaction_hash") or t.get("tx_hash")
        events.append(_evm_event(address, h, _h(t.get("from")), _h(t.get("to")), val, sym,
                                 t.get("timestamp"), explorer))
    return {"chain": chain, "address": address, "balance": bal, "native": native, "events": events}


def _evm_event(me, h, frm, to, amount, sym, ts, explorer) -> dict:
    direction = "in" if (to or "").lower() == me.lower() else "out"
    return {"id": f"{h}:{sym}:{direction}", "hash": h, "direction": direction, "amount": amount,
            "symbol": sym, "counterparty": frm if direction == "in" else to, "ts": _iso(ts),
            "url": explorer + h if h else None}


def evm_token_whales(chain: str, contract: str, min_amount: float, pages: int = 4) -> list[dict]:
    """Recent transfers of a token contract at or above min_amount (in token units).

    Reads the newest `pages` × 50 transfers. Best for mid/small-volume tokens: for USDT/USDC
    that window is only a few minutes of activity.
    """
    base, _, explorer = BLOCKSCOUT[chain]
    items, params = [], None
    for _ in range(pages):
        page = get_json(f"{base}/api/v2/tokens/{contract}/transfers", params=params)
        items += page.get("items", [])
        params = page.get("next_page_params")
        if not params:
            break
    out = []
    for t in items:
        total = t.get("total") or {}
        dec = int(total.get("decimals") or (t.get("token") or {}).get("decimals") or 18)
        try:
            amt = int(total.get("value") or 0) / 10 ** dec
        except (TypeError, ValueError):
            continue
        if amt < min_amount:
            continue
        h = t.get("transaction_hash") or t.get("tx_hash")
        frm, to = t.get("from") or {}, t.get("to") or {}
        out.append({"id": f"{h}:{contract}", "hash": h, "amount": amt,
                    "symbol": (t.get("token") or {}).get("symbol"),
                    "from": frm.get("hash"), "from_label": _label(frm),
                    "to": to.get("hash"), "to_label": _label(to),
                    "ts": _iso(t.get("timestamp")), "url": explorer + h if h else None})
    return out


def _label(addr: dict) -> str | None:
    """Prefer an explorer name tag (e.g. 'Binance 14'), then ENS, then the contract name."""
    tags = (addr.get("metadata") or {}).get("tags") or []
    named = [t["name"] for t in tags if t.get("tagType") == "name" and t.get("name")]
    public = [t.get("display_name") or t.get("label") for t in addr.get("public_tags") or []]
    for cand in named + [p for p in public if p] + [addr.get("ens_domain_name"), addr.get("name")]:
        if cand:
            return cand
    return None


def evm_verify(chain: str, tx_hash: str) -> dict:
    base, native, explorer = BLOCKSCOUT[chain]
    t = get_json(f"{base}/api/v2/transactions/{tx_hash}")
    transfers = []
    for tt in t.get("token_transfers") or []:
        total = tt.get("total") or {}
        try:
            amt = int(total.get("value") or 0) / 10 ** int(total.get("decimals") or 18)
        except (TypeError, ValueError):
            amt = None
        transfers.append({"symbol": (tt.get("token") or {}).get("symbol"), "amount": amt,
                          "from": _h(tt.get("from")), "to": _h(tt.get("to"))})
    return {"chain": chain, "hash": tx_hash, "status": t.get("status") or t.get("result"),
            "block": t.get("block_number") or t.get("block"), "confirmations": t.get("confirmations"),
            "from": _h(t.get("from")), "to": _h(t.get("to")),
            "value": int(t.get("value") or 0) / 1e18, "native": native,
            "fee": int((t.get("fee") or {}).get("value") or 0) / 1e18,
            "timestamp": t.get("timestamp"), "token_transfers": transfers, "url": explorer + tx_hash}


# ---------------------------------------------------------------- Bitcoin
def btc_wallet(address: str, limit: int = 15) -> dict:
    info = get_json(f"{MEMPOOL}/address/{address}")
    cs = info["chain_stats"]
    bal = (cs["funded_txo_sum"] - cs["spent_txo_sum"]) / 1e8
    txs = get_json(f"{MEMPOOL}/address/{address}/txs")[:limit]
    events = []
    for t in txs:
        recv = sum(o.get("value", 0) for o in t["vout"] if o.get("scriptpubkey_address") == address)
        sent = sum((i.get("prevout") or {}).get("value", 0) for i in t["vin"]
                   if (i.get("prevout") or {}).get("scriptpubkey_address") == address)
        net = (recv - sent) / 1e8
        st = t.get("status") or {}
        events.append({"id": t["txid"], "hash": t["txid"], "direction": "in" if net >= 0 else "out",
                       "amount": abs(net), "symbol": "BTC", "counterparty": None,
                       "ts": st.get("block_time"), "confirmed": st.get("confirmed", False),
                       "url": f"https://mempool.space/tx/{t['txid']}"})
    return {"chain": "bitcoin", "address": address, "balance": bal, "native": "BTC", "events": events}


def btc_verify(txid: str) -> dict:
    t = get_json(f"{MEMPOOL}/tx/{txid}")
    st = t.get("status") or {}
    conf = 0
    if st.get("confirmed"):
        tip = int(get_json(f"{MEMPOOL}/blocks/tip/height"))
        conf = tip - st["block_height"] + 1
    outs = [{"to": o.get("scriptpubkey_address"), "btc": o["value"] / 1e8} for o in t["vout"]]
    return {"chain": "bitcoin", "hash": txid, "status": "confirmed" if st.get("confirmed") else "unconfirmed",
            "block": st.get("block_height"), "confirmations": conf, "fee": t.get("fee", 0) / 1e8,
            "outputs": outs[:10], "total_out_btc": sum(o["btc"] for o in outs),
            "url": f"https://mempool.space/tx/{txid}"}


# ---------------------------------------------------------------- Solana
def _rpc(method: str, params: list):
    r = post_json(_sol_rpc(), {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if "error" in r:
        raise ValueError(r["error"])
    return r["result"]


def sol_wallet(address: str, limit: int = 10) -> dict:
    bal = _rpc("getBalance", [address])["value"] / 1e9
    sigs = _rpc("getSignaturesForAddress", [address, {"limit": limit}])
    events = []
    for s in sigs:
        if s.get("err"):
            continue
        try:
            tx = _rpc("getTransaction", [s["signature"], {"encoding": "jsonParsed",
                                                          "maxSupportedTransactionVersion": 0}])
        except Exception:  # noqa: BLE001
            tx = None
        for ev in _sol_deltas(address, tx):
            ev.update({"id": f"{s['signature']}:{ev['symbol']}", "hash": s["signature"],
                       "ts": s.get("blockTime"), "url": f"https://solscan.io/tx/{s['signature']}"})
            events.append(ev)
    return {"chain": "solana", "address": address, "balance": bal, "native": "SOL", "events": events}


def _sol_deltas(address: str, tx: dict | None) -> list[dict]:
    if not tx:
        return []
    meta = tx.get("meta") or {}
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in tx["transaction"]["message"]["accountKeys"]]
    out = []
    if address in keys:
        i = keys.index(address)
        d = (meta["postBalances"][i] - meta["preBalances"][i]) / 1e9
        if abs(d) > 0.001:  # ignore pure fee noise
            out.append({"direction": "in" if d > 0 else "out", "amount": abs(d), "symbol": "SOL",
                        "counterparty": None})
    pre = {(b["mint"], b.get("owner")): b["uiTokenAmount"].get("uiAmount") or 0 for b in meta.get("preTokenBalances") or []}
    post = {(b["mint"], b.get("owner")): b["uiTokenAmount"].get("uiAmount") or 0 for b in meta.get("postTokenBalances") or []}
    for (mint, owner) in set(pre) | set(post):
        if owner != address:
            continue
        d = post.get((mint, owner), 0) - pre.get((mint, owner), 0)
        if d:
            out.append({"direction": "in" if d > 0 else "out", "amount": abs(d),
                        "symbol": KNOWN_MINTS.get(mint, mint[:4] + "…" + mint[-4:]), "counterparty": None})
    return out


KNOWN_MINTS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": "JUP",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "BONK",
}


def sol_verify(signature: str) -> dict:
    tx = _rpc("getTransaction", [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
    if not tx:
        return {"chain": "solana", "hash": signature, "status": "not found"}
    meta = tx.get("meta") or {}
    return {"chain": "solana", "hash": signature, "status": "failed" if meta.get("err") else "success",
            "block": tx.get("slot"), "fee": (meta.get("fee") or 0) / 1e9,
            "timestamp": tx.get("blockTime"), "url": f"https://solscan.io/tx/{signature}"}


# ---------------------------------------------------------------- dispatch
def wallet(chain: str, address: str) -> dict:
    if chain == "bitcoin":
        return btc_wallet(address)
    if chain == "solana":
        return sol_wallet(address)
    if chain in BLOCKSCOUT:
        return evm_wallet(chain, address)
    raise ValueError(f"Unsupported chain '{chain}'. Use bitcoin, solana, or one of {list(BLOCKSCOUT)}")


def verify(chain: str, tx: str) -> dict:
    if chain == "bitcoin":
        return btc_verify(tx)
    if chain == "solana":
        return sol_verify(tx)
    return evm_verify(chain, tx)
