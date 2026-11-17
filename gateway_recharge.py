"""FamPay recharge and admin token management. Single encrypted token, MongoDB-backed orders."""
import asyncio
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO

import requests
from cryptography.fernet import Fernet, InvalidToken
from aiogram import F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pymongo import ReturnDocument

BASE_URL = "https://fampay-api-7msf.onrender.com"
MIN_AMOUNT = Decimal("1")
MAX_AMOUNT = Decimal("100000")

class GatewayState(StatesGroup):
    token = State()
    amount = State()

def register_gateway(dp, bot, db, admin_ids):
    settings = db["gateway_settings"]
    payments = db["gateway_payments"]
    users = db["users"]
    cipher_key = os.getenv("GATEWAY_ENCRYPTION_KEY", "")
    cipher = Fernet(cipher_key.encode()) if cipher_key else None

    def admin(uid):
        if uid in admin_ids:
            return True
        sub = db["subadmins"].find_one({"_id": uid, "active": True})
        return bool(sub and "payments" in sub.get("permissions", []))

    def get_token():
        record = settings.find_one({"_id": "fampay"})
        if not record or not record.get("token"):
            return None
        if cipher is None:
            raise RuntimeError("GATEWAY_ENCRYPTION_KEY is not configured")
        return cipher.decrypt(record["token"].encode()).decode()

    async def request_api(path, data):
        def run():
            response = requests.post(BASE_URL + path, json=data, timeout=25)
            response.raise_for_status()
            return response.json()
        return await asyncio.to_thread(run)

    def gateway_keyboard():
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Add / Replace Token", callback_data="gw_token_add")
        kb.button(text="🗑 Remove Token", callback_data="gw_token_remove")
        kb.button(text="⬅️ Admin Panel", callback_data="admin_panel")
        kb.adjust(1)
        return kb.as_markup()

    @dp.callback_query(F.data == "gw_settings")
    async def gateway_settings(cq):
        if not admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        configured = bool(settings.find_one({"_id": "fampay", "token": {"$exists": True}}))
        await cq.message.edit_text("🔑 FamPay API Token\nStatus: " + ("Configured" if configured else "Not configured"), reply_markup=gateway_keyboard())
        await cq.answer()

    @dp.callback_query(F.data == "gw_token_add")
    async def add_token(cq, state):
        if not admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        if cipher is None:
            return await cq.answer("Set GATEWAY_ENCRYPTION_KEY on Render first", show_alert=True)
        await state.set_state(GatewayState.token)
        await cq.message.edit_text("Send your FamPay API token in this private chat. It will be deleted after reading.")
        await cq.answer()

    @dp.message(StateFilter(GatewayState.token))
    async def save_token(message, state):
        if not admin(message.from_user.id) or message.chat.type != "private":
            await state.clear()
            return
        token = (message.text or "").strip()
        try:
            await message.delete()
        except Exception:
            pass
        if not token.startswith("FAM_") or len(token) > 256:
            return await message.answer("Invalid token format. Try again.")
        # Gateway has no dedicated non-mutating key-validation endpoint.
        # Format is checked here; real validation occurs on first recharge.
        settings.update_one({"_id": "fampay"}, {"$set": {"token": cipher.encrypt(token.encode()).decode(), "updated_at": datetime.now(timezone.utc)}}, upsert=True)
        await state.clear()
        await message.answer("✅ Gateway token saved (encrypted).")

    @dp.callback_query(F.data == "gw_token_remove")
    async def remove_token(cq):
        if not admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        settings.update_one({"_id": "fampay"}, {"$unset": {"token": ""}})
        await cq.answer("Token removed; new recharges disabled.", show_alert=True)

    @dp.callback_query(F.data == "gw_recharge")
    async def recharge(cq, state):
        try:
            token = get_token()
        except (RuntimeError, InvalidToken):
            token = None
        if not token:
            return await cq.answer("Recharge temporarily unavailable.", show_alert=True)
        await state.set_state(GatewayState.amount)
        await cq.message.edit_text("💳 Enter recharge amount in INR (₹1 to ₹100000):")
        await cq.answer()

    @dp.message(StateFilter(GatewayState.amount))
    async def create_recharge(message, state):
        try:
            amount = Decimal((message.text or "").strip())
            if not amount.is_finite() or amount < MIN_AMOUNT or amount > MAX_AMOUNT or amount.as_tuple().exponent < -2:
                raise InvalidOperation
            token = get_token()
            if not token:
                raise ValueError("Gateway not configured")
            response = await request_api("/fam_create", {"api_key": token, "amount": str(amount)})
            if response.get("status") != "success":
                raise ValueError(response.get("message", "Gateway error"))
            data = response["data"]
            order_id = str(data["order_id"])
            payments.insert_one({"_id": order_id, "user_id": message.from_user.id, "amount": str(amount), "status": "pending", "created_at": datetime.now(timezone.utc)})
            kb = InlineKeyboardBuilder()
            kb.button(text="✅ Check Payment", callback_data="gw_check:" + order_id)
            kb.adjust(1)
            qr_url = data.get("qr_url")
            if qr_url and qr_url.startswith(BASE_URL + "/qr_codes/"):
                def fetch_qr():
                    res = requests.get(qr_url, timeout=20)
                    res.raise_for_status()
                    return res.content
                qr = await asyncio.to_thread(fetch_qr)
                await message.answer_photo(BufferedInputFile(qr, filename="payment.png"), caption=f"Pay ₹{amount} within 5 minutes.\nOrder: <code>{order_id}</code>", reply_markup=kb.as_markup())
            else:
                await message.answer(f"Pay ₹{amount}. Order: <code>{order_id}</code>", reply_markup=kb.as_markup())
        except Exception:
            await message.answer("❌ Unable to create payment. Check amount or try again later.")
        finally:
            await state.clear()

    async def expire_order(cq, order_id):
        payments.update_one(
            {"_id": order_id, "status": "pending"},
            {"$set": {"status": "expired", "expired_at": datetime.now(timezone.utc)}},
        )
        try:
            await cq.message.delete()
        except Exception:
            pass
        await cq.message.answer(f"❌ QR Expired\nOrder ID: <code>{order_id}</code>")

    async def announce_paid_order(order_id):
        record = payments.find_one_and_update(
            {"_id": order_id, "status": "paid", "public_notice": {"$exists": False}},
            {"$set": {"public_notice": "sending"}},
            return_document=ReturnDocument.AFTER)
        if not record:
            return
        try:
            await bot.send_message(
                "@SuperOtpZOfficial",
                "🎉 <b>NEW DEPOSIT SUCCESSFUL</b>\n\n"
                f"🆔 <b>Deposit ID:</b> <code>{record.get('deposit_id', order_id)}</code>\n"
                f"💰 <b>Amount:</b> ₹{Decimal(str(record['amount'])):.2f}\n"
                "💳 <b>Method:</b> UPI Automatic\n"
                "✅ <b>Status:</b> Successful", parse_mode="HTML")
        except Exception:
            payments.update_one({"_id": order_id, "public_notice": "sending"},
                                {"$unset": {"public_notice": ""}})
        else:
            payments.update_one({"_id": order_id, "public_notice": "sending"},
                                {"$set": {"public_notice": "sent"}})

    @dp.callback_query(F.data.startswith("gw_check:"))
    async def verify_recharge(cq):
        await cq.answer()
        order_id = cq.data.partition(":")[2]
        order = payments.find_one({"_id": order_id, "user_id": cq.from_user.id})
        if not order:
            return await cq.message.answer("Order not found.")
        if order.get("status") == "paid":
            await announce_paid_order(order_id)
            return await cq.message.answer("✅ Payment Received")
        if order.get("status") == "expired":
            return await cq.message.answer(f"❌ QR Expired\nOrder ID: <code>{order_id}</code>")
        created_at = order.get("created_at")
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        expired = created_at is not None and datetime.now(timezone.utc) >= created_at + timedelta(minutes=5)
        try:
            token = get_token()
            if not token:
                return await cq.message.answer("Gateway unavailable; contact support.")
            result = await request_api("/fam_verify", {"api_key": token, "order_id": order_id})
            if result.get("status") != "success" or result.get("order_id", order_id) != order_id:
                if expired:
                    return await expire_order(cq, order_id)
                return await cq.message.answer("⏳ Payment Not Received Yet")
            # Do not credit an API response which lacks matching payment evidence.
            detail = result.get("data")
            if not isinstance(detail, dict):
                return await cq.message.answer("Payment verification incomplete. Retry later.")
            verified_id = detail.get("order_id", result.get("order_id"))
            if verified_id is None or str(verified_id) != order_id:
                return await cq.message.answer("Payment order mismatch. Contact support.")
            if str(detail.get("status", "success")).lower() in ("pending", "expired", "failed"):
                return await cq.message.answer("⏳ Payment Not Received Yet")
            try:
                verified_amount = Decimal(str(detail["amount"]))
                expected_amount = Decimal(order["amount"])
            except (KeyError, InvalidOperation, ValueError, TypeError):
                return await cq.message.answer("Payment amount not verified. Retry later.")
            if not verified_amount.is_finite() or verified_amount != expected_amount:
                return await cq.message.answer("Amount mismatch. Contact support.")

            amount = float(expected_amount)
            # This user marker is the idempotency ledger for a successful recharge.
            updated = users.update_one(
                {"_id": order["user_id"], "credited_gateway_orders": {"$ne": order_id}},
                {"$inc": {"balance": amount}, "$addToSet": {"credited_gateway_orders": order_id}})
            credited = bool(updated.modified_count) or bool(users.find_one({
                "_id": order["user_id"], "credited_gateway_orders": order_id
            }))
            if not credited:
                return await cq.message.answer("Wallet unavailable; contact support.")

            # A separate idempotency marker permits safe recovery if payment
            # credit succeeded but referral processing previously failed.
            config = (db["admin_settings"].find_one({"_id": "referral"}) or {})
            payer = users.find_one({"_id": order["user_id"]}) or {}
            referrer = payer.get("referred_by")
            try:
                pct = Decimal(str(config.get("percent", 0)))
                if not pct.is_finite() or not 0 <= pct <= 100:
                    pct = Decimal("0")
            except (InvalidOperation, ValueError):
                pct = Decimal("0")
            if isinstance(referrer, int) and referrer != order["user_id"] and pct > 0:
                reward = (expected_amount * pct / 100).quantize(Decimal("0.01"))
                if reward > 0:
                    users.update_one(
                        {"_id": referrer, "credited_referral_gateway_orders": {"$ne": order_id}},
                        {"$inc": {"balance": float(reward)},
                         "$addToSet": {"credited_referral_gateway_orders": order_id}})
            # Finalize only after wallet and referral settlement have completed.
            # Retrying a pending order uses the credit markers instead of double-crediting.
            payments.update_one({"_id": order_id, "status": "pending"}, {
                "$set": {"status": "paid", "paid_at": datetime.now(timezone.utc)}
            })
            await announce_paid_order(order_id)
            try:
                await cq.message.delete()
            except Exception:
                # A deletion failure must not undo a successfully credited payment.
                pass
            await cq.message.answer(f"✅ Payment Received\n₹{amount:.2f} added to your balance.")
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            await cq.message.answer("⏳ Gateway slow. Please try Check Payment again shortly.")
        except Exception:
            await cq.message.answer("Verification unavailable. Try again later.")
