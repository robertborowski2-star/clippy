# Clippy — AI Research Agent

Daily AI & research agent that runs on Raspberry Pi 4 alongside Nova. Sends briefings to Telegram.

## Schedule

| Time | Job | Description |
|------|-----|-------------|
| 07:45 daily | AI & Fringe Science | HN, arXiv, AI news → top findings |
| 16:00 daily | Finance & Geopolitics | Brave Search market data → top findings |
| 21:00 daily | Deep Dive | 350-450 word analysis of best finding |
| Sat 01:00 | Science Roundup | Weekly arXiv/ChemRxiv/EarthArxiv across 5 subjects |

## Setup on NintendoPI

### 1. Copy files to Pi

```bash
scp -r ~/Documents/Projects/Clippy/ pi@NintendoPI:~/clippy-src/
```

### 2. SSH in and install

```bash
ssh pi@NintendoPI

# Install dependencies
cd ~/clippy-src
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.template .env
nano .env
# Fill in: ANTHROPIC_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
```

### 3. Get Telegram credentials

1. Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → copy the token
2. Message your new bot, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat ID

### 4. Test it

```bash
# Run a single job to verify everything works
python main.py --run ai

# Run scheduler only (no Telegram bot interaction)
python main.py --no-bot

# Run with full Telegram bot
python main.py
```

### 5. Set up as systemd service

```bash
sudo tee /etc/systemd/system/clippy.service << 'EOF'
[Unit]
Description=Clippy AI Research Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/clippy-src
ExecStart=/home/pi/clippy-src/venv/bin/python main.py
Restart=always
RestartSec=30
EnvironmentFile=/home/pi/clippy-src/.env

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable clippy
sudo systemctl start clippy
```

### 6. Check logs

```bash
# systemd logs
journalctl -u clippy -f

# Application log
tail -f ~/clippy/clippy.log
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Show help |
| `/ask <question>` | Ask Clippy anything (uses Claude + web search) |
| `/status` | Show recent research activity |
| `/run <ai\|finance\|deep\|science>` | Manually trigger a job |
| `/walnut <name>` | Read a walnut file |

## Walnut System

Findings accumulate in `~/clippy/walnuts/`:
- `ai-tech.md` — AI & fringe science findings
- `finance-geo.md` — Finance & geopolitics findings
- `deep-dives.md` — Deep dive archive
- `physics.md`, `mathematics.md`, `biology.md`, `chemistry.md`, `earth-materials.md` — weekly science sections

Each job reads its walnut before researching (context) and writes new findings after (memory). This makes each day's research smarter than yesterday's.

## File Structure

```
clippy-src/
  agent.py          — Claude API calls with web_search tool
  memory.py         — SQLite + walnut file management
  scheduler.py      — 4 APScheduler cron jobs
  main.py           — Entry point
  telegram_bot.py   — Telegram bot + message delivery
  requirements.txt
  .env

~/clippy/
  clippy.db         — SQLite research log
  clippy.log        — Application log
  walnuts/
    ai-tech.md
    finance-geo.md
    deep-dives.md
```
