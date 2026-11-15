# Super-OtpZ

Telegram bot using Aiogram 3, Telethon, and MongoDB.

## Changes on feature/fampay-admin-panel

- Admin-only /admin panel and admin button in /start.
- Buttons for existing /setprices, /add, /remove, /addcountry, /removecountry, /db and /broadcast workflows.
- Single FamPay API token management from Telegram admin panel (add/replace/remove).
- FamPay automatic recharge: QR creation via POST /fam_create and verification via POST /fam_verify.
- Atomic per-user order-credit guard to prevent duplicate balance increments.
- Legacy manual UPI screenshot and OxaPay recharge modules removed from this branch.

## Required environment variables (when hosting later)

- BOT_TOKEN
- ADMIN_IDS (comma-separated numeric Telegram user IDs)
- MONGO_URI
- API_ID and API_HASH for Telethon workflows
- GATEWAY_ENCRYPTION_KEY (Fernet key; generate securely and keep stable across restarts)

The gateway URL is https://fampay-api-7msf.onrender.com.

**Security:** Keep tokens and secrets out of GitHub. Previously committed credentials should be rotated. The gateway token is encrypted in MongoDB; the encryption key must be provided through Render environment settings. Never lose the encryption key while an encrypted token is stored.

## Running

Install requirements with `pip install -r requirements.txt` and run `python bot.py`.

## Before deployment

1. Validate Python imports and run bot startup in a test environment.
2. Test every admin panel button and confirm non-admin callbacks cannot access admin actions.
3. Test gateway payment creation, QR display, pending/paid/expired statuses, and duplicate checks.
4. Confirm FamPay Gateway persists orders, verified transactions and API keys across restarts.
5. Test behavior when the API token is replaced during an outstanding order.
6. Review exposed credentials, API security, and the Telegram-account session workflow.
7. Configure and test MongoDB Atlas access and Render worker.
