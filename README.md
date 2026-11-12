# Super OtpZ

A Telegram account marketplace bot built with **Python**, **Aiogram 3**, **MongoDB**, and **Telethon**.

The bot provides a Telegram-based interface for browsing available account stock, managing user balances, placing orders, and handling recharge requests. It also includes admin utilities and channel-membership checks.

> **Important:** Review Telegram's terms and applicable laws before operating an account marketplace. Never upload API credentials, bot tokens, database credentials, payment keys, or user session data to a public repository.

## Features

- Telegram bot interface with inline menus.
- User profiles and balance tracking.
- Country-based stock and purchase workflow.
- Admin tools for managing stock, pricing, users, and transactions.
- Required-channel membership verification.
- Balance recharge options:
  - INR / UPI payment flow with QR image and manual review.
  - OxaPay crypto invoice creation and payment-status checking.
- MongoDB-backed user, stock, order, and payment records.
- Telethon integration used by the project’s Telegram-account workflow.

## Project files

| File | Purpose |
|---|---|
| `bot.py` | Main bot handlers and application logic |
| `config.py` | Loads bot token and admin IDs from environment variables |
| `mustjoin.py` | Required-channel membership check and join prompt |
| `recharge_flow.py` | UPI and crypto recharge handlers |
| `oxapay.py` | OxaPay invoice and payment-status API helpers |
| `db.py` | SQLAlchemy database models (separate from the MongoDB collections used in `bot.py`) |
| `requirements.txt` | Python dependencies |
| `runtime.txt` | Python runtime declaration |
| `__main__.py` | Package entry-point helper |

## Requirements

- Python 3.10 or newer.
- A Telegram bot token from [@BotFather](https://t.me/BotFather).
- A MongoDB database.
- Telegram API ID and API hash from [my.telegram.org](https://my.telegram.org).
- An OxaPay merchant API key if crypto recharge is enabled.
- A UPI ID and a QR image if UPI recharge is enabled.

## Configuration

Set these environment variables in your hosting provider:

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | Yes | Telegram bot token |
| `ADMIN_IDS` | Yes | Admin Telegram user IDs, comma-separated |
| `MONGO_URI` | Yes | MongoDB connection URI used by `bot.py` |
| `API_ID` | When Telethon workflow is used | Telegram API ID |
| `API_HASH` | When Telethon workflow is used | Telegram API hash |

Example format (replace the sample values with your own; do not commit real credentials):

```env
BOT_TOKEN=123456:replace_with_your_bot_token
ADMIN_IDS=123456789,987654321
MONGO_URI=mongodb+srv://username:password@cluster.example.mongodb.net/
API_ID=12345678
API_HASH=replace_with_your_api_hash
```

The current source also contains additional settings that must be reviewed before deployment:

- `mustjoin.py`: required channel IDs and invite links.
- `recharge_flow.py`: UPI ID, INR/USDT conversion rate, minimum crypto amount, and QR image path (`QR.jpg`).
- `oxapay.py`: replace the placeholder API key with a securely configured merchant key before enabling crypto payments. Prefer loading it from an environment variable rather than hard-coding it.
- `bot.py`: review the bot username, support/updates links, and any remaining deployment-specific values.

**Do not publish real credentials or private invite links.** If any real token, API hash, database password, or payment key has been committed, rotate it.

## Installation

1. Clone this repository.
2. Create and activate a virtual environment.
3. Install the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Configure the environment variables listed above.
5. Review the project-specific settings and add the UPI QR image if UPI recharge is enabled.
6. Start the bot using the entry point configured for your deployment. Verify the actual startup command for your host before deploying; this repository does not currently include a deployment-specific Procfile.

## Deployment checklist

- [ ] Set all required environment variables.
- [ ] Confirm MongoDB network access and database permissions.
- [ ] Confirm the bot is an administrator in each required channel so membership checks can work.
- [ ] Configure the UPI ID and upload the correct QR image, if using UPI.
- [ ] Configure and test OxaPay credentials, if using crypto.
- [ ] Keep secrets out of source control and rotate any credentials previously exposed.
- [ ] Test user, admin, recharge, and purchase flows with a test account before going live.

## Notes

The repository currently contains both MongoDB-based application code and a separate SQLAlchemy model file. The main bot code uses MongoDB collections; do not assume that the SQLAlchemy models in `db.py` are wired into the running bot.

This README describes the files and configuration currently present in the repository. Update it whenever the code, environment variables, or deployment process changes.
