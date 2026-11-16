"""Telegram admin menu; reuses existing command handlers."""
from aiogram import F
from aiogram.types import Message
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

ACTIONS = [
    ("💰 Set Sell Prices", "setprices"),
    ("💳 Add Balance", "addbalance"),
    ("➖ Deduct Balance", "deductbalance"),
    ("➕ Add Number", "add"),
    ("➖ Remove Number", "remove"),
    ("🌍 Add Country", "addcountry"),
    ("🗑 Remove Country", "removecountry"),
    ("🗄 Database View", "db"),
    ("📢 Broadcast", "broadcast"),
]

class AdminBalance(StatesGroup):
    waiting_user = State()
    waiting_amount = State()

class AdminBroadcast(StatesGroup):
    waiting_message = State()

def register_admin_panel(dp, bot, admin_ids, handlers):
    def is_admin(uid):
        return uid in admin_ids

    def menu():
        kb = InlineKeyboardBuilder()
        for label, command in ACTIONS:
            kb.button(text=label, callback_data="admin_do:" + command)
        kb.button(text="🔑 Gateway API Settings", callback_data="gw_settings")
        kb.button(text="⬅️ Main Menu", callback_data="back_main")
        kb.adjust(2, 2, 2, 1, 1, 1)
        return kb.as_markup()

    @dp.message(Command("admin"))
    async def admin_command(message):
        if not is_admin(message.from_user.id):
            return await message.answer("❌ Not authorized.")
        await message.answer("🛡 <b>Admin Panel</b>", reply_markup=menu())

    @dp.callback_query(F.data == "admin_panel")
    async def admin_callback(cq):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        await cq.message.answer("🛡 <b>Admin Panel</b>", reply_markup=menu())
        await cq.answer()

    @dp.callback_query(F.data.startswith("admin_do:"))
    async def admin_action(cq, state):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        command = cq.data.partition(":")[2]
        if command in {"addbalance", "deductbalance"}:
            await state.clear()
            await state.update_data(balance_operation=command)
            await state.set_state(AdminBalance.waiting_user)
            await cq.message.answer("💳 Send the Telegram numeric User ID. /cancel to stop.")
        elif command == "broadcast":
            await state.set_state(AdminBroadcast.waiting_message)
            await cq.message.answer("📢 Send the message to broadcast. /cancel to stop.")
        elif command in handlers:
            # Callback messages are authored by the bot. Override the sender for
            # the existing command handler's authorization check.
            msg = cq.message.model_copy(update={"from_user": cq.from_user})
            handler = handlers[command]
            if command in {"db", "removecountry"}:
                await handler(msg)
            else:
                await handler(msg, state)
        await cq.answer()

    @dp.message(StateFilter(AdminBroadcast.waiting_message), Command("cancel"))
    async def cancel_broadcast(message, state):
        await state.clear()
        await message.answer("Broadcast cancelled.")

    @dp.message(StateFilter(AdminBroadcast.waiting_message))
    async def send_broadcast(message, state):
        if not is_admin(message.from_user.id):
            await state.clear()
            return
        await state.clear()
        await message.answer("📢 Broadcasting...")
        await handlers["broadcast_panel"](message)

    @dp.message(StateFilter(AdminBalance.waiting_user), Command("cancel"))
    @dp.message(StateFilter(AdminBalance.waiting_amount), Command("cancel"))
    async def cancel_balance(message: Message, state):
        await state.clear()
        await message.answer("❌ Add Balance cancelled.")

    @dp.message(StateFilter(AdminBalance.waiting_user))
    async def balance_user(message: Message, state):
        if not is_admin(message.from_user.id):
            await state.clear()
            return await message.answer("❌ Not authorized.")
        value = (message.text or "").strip()
        if not value.isdecimal() or not (0 < int(value) < 10**16):
            return await message.answer("❌ Enter a valid numeric Telegram User ID.")
        await state.update_data(balance_target=int(value))
        await state.set_state(AdminBalance.waiting_amount)
        operation = (await state.get_data()).get("balance_operation")
        await message.answer(f"💰 Enter amount to {'DEDUCT' if operation == 'deductbalance' else 'ADD'} in INR (example: 100). /cancel to stop.")

    @dp.message(StateFilter(AdminBalance.waiting_amount))
    async def balance_amount(message: Message, state):
        if not is_admin(message.from_user.id):
            await state.clear()
            return await message.answer("❌ Not authorized.")
        from decimal import Decimal, InvalidOperation
        from pymongo import ReturnDocument
        raw = (message.text or "").strip()
        try:
            amount = Decimal(raw)
            if not amount.is_finite() or amount <= 0 or amount > 100000:
                raise InvalidOperation()
            if amount.as_tuple().exponent < -2:
                raise InvalidOperation()
        except (InvalidOperation, ValueError):
            return await message.answer("❌ Enter a positive amount up to ₹100000, max 2 decimal places.")
        data = await state.get_data()
        target = data["balance_target"]
        users_col = handlers["users_col"]
        # Only existing users can be credited, avoiding accidental new accounts.
        deduct = data.get("balance_operation") == "deductbalance"
        condition = {"_id": target, "balance": {"$gte": float(amount)}} if deduct else {"_id": target}
        updated = users_col.find_one_and_update(
            condition, {"$inc": {"balance": -float(amount) if deduct else float(amount)}},
            return_document=ReturnDocument.AFTER
        )
        if not updated:
            return await message.answer("❌ User not found or insufficient balance for deduction. Check User ID/amount or /cancel.")
        await state.clear()
        await message.answer(
            f"✅ Balance {'Deducted' if deduct else 'Added'}!\\n🆔 User ID: <code>{target}</code>\\n"
            f"{'➖ Deducted' if deduct else '➕ Added'}: ₹{amount:.2f}\\n💰 New Balance: ₹{updated.get('balance', 0):.2f}",
            parse_mode="HTML"
        )
        try:
            await bot.send_message(target, f"💰 Your wallet has been {'debited' if deduct else 'credited'} ₹{amount:.2f} by admin.")
        except Exception:
            pass
