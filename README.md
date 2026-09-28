# Chainsense Bot

Your background crypto analyst. It sends two things to Telegram:

- **Daily brief (6 AM Lagos):** market cap, majors, top-100 gainers/losers, trending coins, Fear & Greed, stablecoin supply and de-pegs, DeFi TVL by chain, Bitcoin fees/hashrate, your watchlist, whale transfers verified on-chain, headlines, and (optionally) Claude-written analyst notes with video angles for Chainsense.
- **Watch alerts (every 10–30 min):** new transactions on your wallets, big price swings on your tokens, and large USDT/USDC transfers — each with an explorer link so you can verify it.

Everything uses free, keyless public data: CoinGecko, DefiLlama, alternative.me, mempool.space, Blockscout (Ethereum, Base, Arbitrum, Optimism, Polygon, Gnosis), Solana RPC, and news RSS feeds.

## 1. Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
cp .env.example .env
```

## 2. Create your Telegram bot (3 minutes)

1. In Telegram, message **@BotFather** → `/newbot` → pick a name → copy the token into `TELEGRAM_BOT_TOKEN` in `.env`.
2. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy `"chat":{"id": ...}` into `TELEGRAM_CHAT_ID`.
   (For a channel: add the bot as an admin and use the channel's `@username` or `-100…` id.)

## 3. Add your watchlist

Edit `config.yaml` → `watchlist`: tokens (CoinGecko "API ID"), wallets (chain + address), and token contracts to watch for whale moves.

## 4. Try it

```bash
python main.py daily --dry-run          # print today's brief
python main.py daily                    # send it to Telegram
python main.py watch                    # first run records the baseline; later runs alert on new moves
python main.py verify eth 0x<txhash>    # verify any transaction (eth, base, arbitrum, optimism, polygon, gnosis, bitcoin, solana)
python main.py wallet bitcoin bc1q...   # balance + recent movements for any wallet
```

## 5. Run it in the background (pick one)

**A. GitHub Actions — free, no server.** Push this folder to a **private** repo. In *Settings → Secrets and variables → Actions*, add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and optionally `ANTHROPIC_API_KEY`, `COINGECKO_API_KEY`, `SOLANA_RPC_URL`. To keep wallet addresses out of the repo, paste your whole `config.yaml` into a secret named `CHAINSENSE_CONFIG_YAML`. The brief runs at 05:45 Lagos and alerts every 30 minutes. Use *Actions → Run workflow* to test.
Note: private repos get 2,000 free Action minutes a month; the 30-minute watch uses roughly 1,500. For faster alerts use option B.

**B. A small VPS (any $4–6/month Linux box).**
```bash
sudo useradd -r -m chainsense
sudo git clone <your-repo> /opt/chainsense-bot && cd /opt/chainsense-bot
sudo python3 -m venv .venv && sudo .venv/bin/pip install -r requirements.txt
# add config.yaml and .env, then:
sudo chown -R chainsense /opt/chainsense-bot
sudo cp deploy/chainsense.service /etc/systemd/system/
sudo systemctl enable --now chainsense
journalctl -u chainsense -f     # logs
```
`serve` mode checks every 10 minutes and sends the brief once a day at `schedule.daily_time`.

**C. Cron (Linux/macOS):**
```
45 5 * * *   cd /path/to/chainsense-bot && .venv/bin/python main.py daily
*/10 * * * * cd /path/to/chainsense-bot && .venv/bin/python main.py watch
```
(Set the machine's timezone to Africa/Lagos, or adjust the hour.)

## Notes

- **Analyst notes** only appear when `ANTHROPIC_API_KEY` is set. The model only sees the collected data and is told not to invent numbers.
- **Headlines are "reported", not verified.** On-chain items (wallet moves, whale transfers, `verify`) are read straight from the chain.
- Public APIs rate-limit. If a source fails, the brief still sends and lists what failed at the bottom.
- For research and content only — not financial advice.
