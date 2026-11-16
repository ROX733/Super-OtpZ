# Advanced Admin Panel — deployment gate

This branch changes live payment and account-purchase paths. Do **not** deploy automatically.

## Before release
1. Run `python -m compileall -q bot.py admin_menu.py gateway_recharge.py manual_recharge.py`.
2. Run `python -m unittest discover -s tests -p 'test_admin_integration.py' -v`.
3. On a **staging** Telegram bot and staging MongoDB, test:
   - Owner and payment-only/stock-only subadmins; unauthorized callbacks and FSM inputs.
   - User manual payment method selection, optional QR, INR validation, proof upload.
   - Two admins approving same deposit concurrently: exactly one wallet credit.
   - Reject vs approve race; retry an interrupted `processing` deposit.
   - Automatic FamPay UPI recharge and user `gw_check:` callbacks.
   - Referrer credited exactly once for manual and gateway deposits.
   - Discounted purchase, insufficient funds, reservation rollback.
   - Maintenance and ban middleware.
   - Backup JSON, restore on staging, account bio change.
   - All admin navigation and broadcast text/photo/video/buttons.
4. Verify `API_ID`, `API_HASH`, `GATEWAY_ENCRYPTION_KEY`, `MONGO_URI` are set.
5. Back up production MongoDB and obtain explicit approval before restarting VPS.

## Known limitation
MongoDB writes for stock reservation, wallet debit and order insertion are not in a multi-document transaction; a crash between these steps can leave a partial purchase. Manual deposit approval uses an idempotent per-user marker and a recoverable processing status but also needs staging concurrency testing.

**Do not label this branch production-ready until the staging checklist passes.**
