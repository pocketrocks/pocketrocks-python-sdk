# PocketRocks bot — starter project

This is a ready-to-run template for **your own bot**. It's the recommended way
to use the PocketRocks SDK: you copy this folder out to its own location, install
the SDK into a private virtual environment, add your keys, and run.

> You do **not** build your bot inside the SDK's source repo. This folder is a
> starting point you take with you.

Follow these steps top to bottom. They assume only that you have **Python 3.10
or newer** installed (`python3 --version` to check).

---

## 1. Copy this folder to where you want your bot to live

```bash
cp -r starter ~/my-pocketrocks-bot
cd ~/my-pocketrocks-bot
```

(Rename `my-pocketrocks-bot` to anything you like.)

## 2. Create and activate a virtual environment

A virtual environment (venv) keeps this bot's dependencies isolated from the
rest of your system.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

Your prompt should now show `(.venv)`. Do this every time you open a new
terminal to work on the bot.

## 3. Install the SDK

```bash
pip install -r requirements.txt
```

This downloads the PocketRocks SDK and everything it needs.

## 4. Add your keys

```bash
cp .env.example .env
```

Open `.env` and paste in the values from your PocketRocks dashboard:

```
POCKETROCKS_API_KEY=your-real-key
POCKETROCKS_BOT_ID=your-bot-id
POCKETROCKS_SERVER_URL=wss://pocketrocks.xyz
```

`.env` is git-ignored, so your secret key stays local.

## 5. Run it

```bash
python bot.py
```

You should see the SDK connect and start logging. Press **Ctrl+C** to stop.

If it exits immediately, check the message:
- `api_key is required` / `bot_id is required` → your `.env` isn't filled in (or
  you're in the wrong folder).
- A connection/`401` error → wrong key or `POCKETROCKS_SERVER_URL`.

---

## 6. Make it your bot

Open [`bot.py`](bot.py) and edit the `choose_decision` method. That's the one
function that decides how your bot plays. The three moves you can return:

```python
BotDecision.pass_turn()                   # do nothing this turn
BotDecision.submit_bid(amount)            # bid `amount`
BotDecision.select_info_to_reveal(index)  # reveal a card
```

Everything else — connecting, authentication, heartbeats, reconnects, handling
many games at once — is done for you by the SDK.

For the full list of what `context` gives you and other hooks you can override,
see the main [SDK README](../README.md#bot-api-reference).

## 7. Train it locally before you go live

```bash
python train.py
```

This runs your bot against the built-in sample opponents entirely offline —
no server, no `.env`, no credentials needed — and prints a win-rate summary,
so you can tell whether an edit actually helped before spending a real game on
it. Keep looping steps 6 and 7 until you're happy, then go live again with
`python bot.py`.
