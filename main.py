#!/usr/bin/env python3
"""Chainsense crypto intelligence bot.

  python main.py daily             # full daily brief → Telegram
  python main.py watch             # one watch pass (new wallet moves, price swings, whales)
  python main.py serve             # keep running: watch every N min + daily brief at the set time
  python main.py verify eth 0x...  # verify a transaction on-chain (eth/base/arbitrum/optimism/polygon/gnosis/bitcoin/solana)
  python main.py wallet solana <address>   # show a wallet's balance and recent movements
Add --dry-run to print instead of sending.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

from chainsense import onchain
from chainsense.alerts import run_watch
from chainsense.brief import LAGOS, run_daily
from chainsense.core import State, load_config


def main() -> int:
    ap = argparse.ArgumentParser(description="Chainsense crypto intelligence bot")
    ap.add_argument("command", choices=["daily", "watch", "serve", "verify", "wallet"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--dry-run", action="store_true", help="print instead of sending to Telegram")
    ap.add_argument("--config", help="path to config.yaml")
    a = ap.parse_args()
    cfg = load_config(a.config)

    if a.command == "daily":
        run_daily(cfg, State(), dry_run=a.dry_run)
    elif a.command == "watch":
        run_watch(cfg, State(), dry_run=a.dry_run)
    elif a.command in ("verify", "wallet"):
        if len(a.args) != 2:
            ap.error(f"usage: {a.command} <chain> <{'tx hash' if a.command == 'verify' else 'address'}>")
        fn = onchain.verify if a.command == "verify" else onchain.wallet
        print(json.dumps(fn(a.args[0].lower(), a.args[1]), indent=2, default=str))
    elif a.command == "serve":
        serve(cfg, a.dry_run)
    return 0


def serve(cfg: dict, dry_run: bool) -> None:
    every = int((cfg.get("schedule") or {}).get("watch_every_minutes", 10)) * 60
    hh, mm = map(int, str((cfg.get("schedule") or {}).get("daily_time", "06:00")).split(":"))
    print(f"Serving: watch every {every // 60} min, daily brief at {hh:02d}:{mm:02d} Lagos time.")
    while True:
        now = datetime.now(LAGOS)
        try:
            st = State()
            if (now.hour, now.minute) >= (hh, mm) and st.get("last_daily") != now.date().isoformat():
                st.set("last_daily", now.date().isoformat())
                run_daily(cfg, st, dry_run=dry_run)
            run_watch(cfg, State(), dry_run=dry_run)
        except Exception as e:  # noqa: BLE001 — keep the loop alive
            print(f"[{now:%H:%M}] error: {e}", file=sys.stderr)
        time.sleep(every)


if __name__ == "__main__":
    sys.exit(main())
