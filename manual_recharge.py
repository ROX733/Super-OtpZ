"""Manual recharge: user proof submission, atomic admin approval and custom INR amount."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape
from bson import ObjectId
from pymongo import ReturnDocument
from aiogram import F
from aiogram.filters import StateFilter, Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

class ManualRecharge(StatesGroup):
    amount = State()
    proof = State()
    custom = State()

def register_manual_recharge(dp, bot, db, admin_ids):
    methods = db["manual_payment_methods"]
    requests = db["manual_deposits"]
    users = db["users"]
    settings = db["admin_settings"]

    def enabled():
        return bool((settings.find_one({"_id": "manual_payments"}) or {}).get("enabled", False))

    def admin(uid):
        if uid in admin_ids:
            return True
        sub = db["subadmins"].find_one({"_id": uid, "active": True})
        return bool(sub and "payments" in sub.get("permissions", []))

    def money(raw):
        try:
            amount = Decimal(str(raw))
            if not amount.is_finite() or amount < Decimal("1") or amount > Decimal("100000") or amount.as_tuple().exponent < -2:
                raise InvalidOperation()
            return amount
        except (InvalidOperation, ValueError):
            return None

    @dp.callback_query(F.data == "recharge")
    async def recharge_options(cq):
        kb = InlineKeyboardBuilder()
        kb.button(text="⚡ Automatic UPI", callback_data="gw_recharge")
        if enabled() and methods.count_documents({"enabled": {"$ne": False}}):
            kb.button(text="💳 Manual Payment", callback_data="manual_recharge")
        kb.button(text="⬅️ Main Menu", callback_data="back_main")
        kb.adjust(1)
        await cq.message.edit_text("💳 <b>Recharge Wallet</b>\\nSelect payment type:", reply_markup=kb.as_markup())
        await cq.answer()

    @dp.callback_query(F.data == "manual_recharge")
    async def choose_method(cq):
        if not enabled():
            return await cq.answer("Manual recharge unavailable", show_alert=True)
        available = list(methods.find({"enabled": {"$ne": False}}).limit(40))
        kb = InlineKeyboardBuilder()
        for method in available:
            kb.button(text=method["name"][:45], callback_data=f"mr:method:{method['_id']}")
        kb.button(text="⬅️ Back", callback_data="recharge")
        kb.adjust(1)
        await cq.message.edit_text("💳 Select a manual payment method:" if available else "No manual methods available.",
                                   reply_markup=kb.as_markup())
        await cq.answer()

    @dp.callback_query(F.data.startswith("mr:method:"))
    async def method_selected(cq, state):
        if not enabled():
            return await cq.answer("Manual recharge unavailable", show_alert=True)
        try:
            method = methods.find_one({"_id": ObjectId(cq.data.split(":")[2])})
        except Exception:
            method = None
        if not method or method.get("enabled") is False:
            return await cq.answer("Payment method unavailable", show_alert=True)
        await state.set_state(ManualRecharge.amount)
        await state.update_data(method_id=str(method["_id"]), panel_chat=cq.message.chat.id,
                                panel_message=cq.message.message_id)
        await cq.message.edit_text(f"💳 <b>{escape(method['name'])}</b>\\nEnter amount in INR (₹1–₹100000).\\n/cancel to stop.")
        await cq.answer()

    @dp.message(StateFilter(ManualRecharge.amount, ManualRecharge.proof, ManualRecharge.custom), Command("cancel"))
    async def cancel(message, state):
        await state.clear()
        await message.answer("Cancelled.")

    @dp.message(StateFilter(ManualRecharge.amount))
    async def amount_received(message, state):
        amount = money((message.text or "").strip())
        if amount is None:
            return await message.answer("❌ Enter a valid INR amount (₹1–₹100000).")
        data = await state.get_data()
        method = methods.find_one({"_id": ObjectId(data["method_id"])})
        if not enabled() or not method or method.get("enabled") is False:
            await state.clear()
            return await message.answer("Method no longer available.")
        await state.update_data(amount=str(amount))
        await state.set_state(ManualRecharge.proof)
        text = f"💳 <b>{escape(method['name'])}</b>\\nAmount: ₹{amount:.2f}\\n\\n{escape(method['caption'])}\\n\\nSend payment proof screenshot. /cancel to stop."
        if method.get("qr_file_id"):
            await bot.send_photo(message.chat.id, method["qr_file_id"], caption=text)
        else:
            await bot.edit_message_text(chat_id=data["panel_chat"], message_id=data["panel_message"], text=text)

    @dp.message(StateFilter(ManualRecharge.proof))
    async def proof_received(message, state):
        if not message.photo:
            return await message.answer("❌ Send a screenshot/photo of payment proof.")
        data = await state.get_data()
        method = methods.find_one({"_id": ObjectId(data["method_id"])})
        if not method or method.get("enabled") is False or not enabled():
            await state.clear()
            return await message.answer("Payment method unavailable.")
        doc = {"user_id": message.from_user.id, "amount": data["amount"], "method_id": data["method_id"],
               "method_name": method["name"], "proof": message.photo[-1].file_id,
               "status": "pending", "created_at": datetime.now(timezone.utc)}
        rid = requests.insert_one(doc).inserted_id
        kb = InlineKeyboardBuilder()
        kb.button(text=f"✅ Accept ₹{data['amount']}", callback_data=f"mr:approve:{rid}")
        kb.button(text="❌ Reject", callback_data=f"mr:reject:{rid}")
        kb.button(text="📝 Custom Amount", callback_data=f"mr:custom:{rid}")
        kb.adjust(1)
        caption = (f"🆕 <b>NEW DEPOSIT REQUEST</b>\\n"
                   f"ID: <code>{rid}</code>\\nUser: <code>{message.from_user.id}</code>\\n"
                   f"Amount: ₹{data['amount']}\\nMethod: {escape(method['name'])}")
        delivered = 0
        for uid in admin_ids:
            try:
                await bot.send_photo(uid, doc["proof"], caption=caption, reply_markup=kb.as_markup())
                delivered += 1
            except Exception:
                pass
        await state.clear()
        await message.answer(f"✅ Deposit request submitted. Reference: <code>{rid}</code>. Await admin review.")
        if not delivered:
            await message.answer("⚠️ Admin notification unavailable. Contact support with your reference.")

    async def settle(cq, rid, approved, amount=None):
        try:
            oid = ObjectId(rid)
        except Exception:
            return await cq.answer("Invalid request", show_alert=True)
        doc = requests.find_one({"_id": oid})
        if not doc or doc.get("status") not in ("pending", "processing"):
            return await cq.answer("Already processed or missing", show_alert=True)
        if approved:
            credit = money(amount if amount is not None else doc.get("approved_amount", doc["amount"]))
            if credit is None:
                return await cq.answer("Invalid amount", show_alert=True)
            if doc["status"] == "pending":
                claimed = requests.find_one_and_update(
                    {"_id": oid, "status": "pending"},
                    {"$set": {"status": "processing", "approved_amount": str(credit),
                              "reviewed_by": cq.from_user.id}},
                    return_document=ReturnDocument.AFTER)
                if not claimed:
                    return await cq.answer("Another admin is reviewing this request", show_alert=True)
            else:
                credit = money(doc["approved_amount"])
            # Idempotent wallet credit. A processing record can be retried safely.
            result = users.update_one(
                {"_id": doc["user_id"], "credited_manual_deposits": {"$ne": str(oid)}},
                {"$inc": {"balance": float(credit)}, "$addToSet": {"credited_manual_deposits": str(oid)}})
            if not result.modified_count and not users.find_one(
                    {"_id": doc["user_id"], "credited_manual_deposits": str(oid)}):
                return await cq.answer("User missing; contact owner", show_alert=True)
            # Referral commission is paid once per successful deposit, never per retry.
            pct_record = settings.find_one({"_id": "referral"}) or {}
            payer = users.find_one({"_id": doc["user_id"]}) or {}
            referrer = payer.get("referred_by")
            try:
                pct = Decimal(str(pct_record.get("percent", 0)))
                if not pct.is_finite() or not 0 <= pct <= 100:
                    pct = Decimal("0")
            except (InvalidOperation, ValueError):
                pct = Decimal("0")
            if isinstance(referrer, int) and referrer != doc["user_id"] and pct > 0:
                reward = (credit * pct / 100).quantize(Decimal("0.01"))
                if reward > 0:
                    users.update_one(
                        {"_id": referrer, "credited_referral_deposits": {"$ne": str(oid)}},
                        {"$inc": {"balance": float(reward)},
                         "$addToSet": {"credited_referral_deposits": str(oid)}})
            # Mark completed only after both wallet and referral have settled.
            # If processing is interrupted, approval is safely retriable.
            requests.update_one({"_id": oid, "status": "processing"},
                                {"$set": {"status": "approved",
                                          "reviewed_at": datetime.now(timezone.utc)}})
            status = f"✅ Approved ₹{credit:.2f}"
        else:
            updated = requests.update_one({"_id": oid, "status": "pending"},
                {"$set": {"status": "rejected", "reviewed_by": cq.from_user.id,
                          "reviewed_at": datetime.now(timezone.utc)}})
            if not updated.modified_count:
                return await cq.answer("Already processed", show_alert=True)
            status = "❌ Rejected"
        try:
            await bot.send_message(doc["user_id"], f"Deposit {status}. Reference: <code>{oid}</code>")
        except Exception:
            pass
        await cq.message.edit_caption(caption=(cq.message.caption or "") + f"\\n\\n{status}",
                                      reply_markup=None)
        await cq.answer(status)

    @dp.callback_query(F.data.startswith("mr:approve:"))
    async def approve(cq):
        if not admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        await settle(cq, cq.data.split(":")[2], True)

    @dp.callback_query(F.data.startswith("mr:reject:"))
    async def reject(cq):
        if not admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        await settle(cq, cq.data.split(":")[2], False)

    @dp.callback_query(F.data.startswith("mr:custom:"))
    async def custom(cq, state):
        if not admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        rid = cq.data.split(":")[2]
        try:
            doc = requests.find_one({"_id": ObjectId(rid), "status": "pending"})
        except Exception:
            doc = None
        if not doc:
            return await cq.answer("Request unavailable", show_alert=True)
        await state.set_state(ManualRecharge.custom)
        await state.update_data(custom_rid=rid, custom_chat=cq.message.chat.id,
                                custom_message=cq.message.message_id)
        await cq.message.edit_caption(caption=(cq.message.caption or "") + "\\n\\n📝 Send custom approved INR amount.")
        await cq.answer()

    @dp.message(StateFilter(ManualRecharge.custom))
    async def custom_amount(message, state):
        if not admin(message.from_user.id):
            await state.clear()
            return
        amount = money((message.text or "").strip())
        if amount is None:
            return await message.answer("❌ Enter amount ₹1–₹100000.")
        data = await state.get_data()
        # Reuse settlement with an admin-owned lightweight callback proxy.
        class CallbackProxy:
            from_user = message.from_user
            class Msg:
                caption = "🆕 Deposit request"
                async def edit_caption(self, **kwargs):
                    await bot.edit_message_caption(chat_id=data["custom_chat"],
                        message_id=data["custom_message"], **kwargs)
            message = Msg()
            async def answer(self, *args, **kwargs):
                pass
        await settle(CallbackProxy(), data["custom_rid"], True, amount)
        await state.clear()

