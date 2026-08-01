# RGUKT T&P Notice → Telegram Bot

Monitors the [RGUKT Basar Training & Placement Cell notice board](https://hub.rgukt.ac.in/hub/tnp/index) and automatically forwards new notices to a Telegram channel/group.

## Features

- **Automatic polling** — checks for new notices every 5 minutes (configurable)
- **Smart deduplication** — each notice is sent only once, tracked via a local JSON file
- **Rich formatting** — HTML bold title, full notice text, separated `URL:` and `Attachment:` links
- **Attachment preview** — attachment links trigger Telegram's downloadable file preview card at the bottom of the message
- **Safety overflow protection** — handles long notices with clean paragraph trimming & explicit notice link guidance
- **First-run safety** — records existing notices as "seen" without blasting the channel
- **Resilient** — handles request failures, parsing errors, and Telegram API errors gracefully

---

## Quick Start

### 1. Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts to name your bot
3. Copy the **bot token** (looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

### 2. Set Up Your Channel / Group

1. Create a Telegram **channel** or **group**
2. Add your bot as an **administrator** (it needs permission to send messages)
3. Get the **chat ID**:
   - **Public channel**: Use the channel username, e.g., `@rgukt_tnp_cell_notice_bot`
   - **Private channel/group**:
     1. Add the bot to the channel/group
     2. Send any message in the channel
     3. Open `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
     4. Look for `"chat":{"id":-100XXXXXXXXXX}` — that negative number is your chat ID

### 3. Enable Comments (Optional)

To enable the **"Leave a Comment"** section under every notice post in Telegram:
1. Open your channel in Telegram → Tap Channel Header → **Edit** (Pencil icon)
2. Tap **Discussion** → Select **Create a New Group** (or choose an existing group)
3. Save changes.

---

### 4. Installation & Local Run

```bash
cd tnp_bot
pip install -r requirements.txt
```

Set environment variables:

```bash
# Linux / macOS
export TELEGRAM_BOT_TOKEN="your_bot_token_here"
export TELEGRAM_CHAT_ID="@your_channel_or_chat_id"

# Windows (PowerShell)
$env:TELEGRAM_BOT_TOKEN = "your_bot_token_here"
$env:TELEGRAM_CHAT_ID = "@your_channel_or_chat_id"
```

**Run once** (good for cron / testing):
```bash
python main.py
```

**Continuous polling** (runs forever):
```bash
python main.py --loop
```

**Debug mode** (dumps raw HTML to `debug_dump.html`):
```bash
python main.py --debug
```

---

## Free 24/7 Hosting Options

### Option A: Render.com (Background Worker — Recommended)

1. Push your code to a GitHub repository.
2. Sign up on [Render.com](https://render.com).
3. Click **New +** → Select **Background Worker**.
4. Connect your GitHub repository.
5. Configuration settings:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py --loop`
6. Add Environment Variables:
   - `TELEGRAM_BOT_TOKEN`: `your_bot_token`
   - `TELEGRAM_CHAT_ID`: `@your_channel_username`
7. Click **Create Background Worker**.

### Option B: GitHub Actions (Serverless Cron)

Add `.github/workflows/poll.yml` to your repository:

```yaml
name: RGUKT T&P Bot Poll

on:
  schedule:
    - cron: '*/15 * * * *'
  workflow_dispatch:

jobs:
  poll:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - name: Run Bot
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python main.py
      - name: Commit State
        run: |
          git config --global user.name 'github-actions[bot]'
          git config --global user.email 'github-actions[bot]@users.noreply.github.com'
          git add sent_notices.json
          git diff --quiet && git diff --staged --quiet || (git commit -m "Update sent_notices.json" && git push)
```

---

## Project Structure

```
tnp_bot/
├── config.py             # Environment configuration & sane defaults
├── scraper.py            # Fetch & parse notice cards from RGUKT T&P
├── state.py              # JSON deduplication tracker (sent_notices.json)
├── telegram_sender.py    # Formatter & Telegram Bot API client
├── main.py               # Main CLI entry point (--loop, --debug)
├── requirements.txt      # Python dependencies
├── .gitignore            # Excludes bytecode, secrets & debug dumps
└── README.md             # Setup & deployment guide
```

---

## Troubleshooting

### 0 notices parsed
The RGUKT site template may have changed. Run with `--debug` to dump the raw HTML:

```bash
python main.py --debug
```

Inspect `debug_dump.html` and update the selectors in `scraper.py` accordingly.

### Telegram messages not sending
- Ensure the bot is an **admin** in the channel/group
- For private channels, use the **numeric chat ID** (negative number), not a username
- Check your bot token is correct: visit `https://api.telegram.org/bot<TOKEN>/getMe`
