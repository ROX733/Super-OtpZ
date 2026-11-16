"""Telegram admin menu; reuses existing command handlers."""
from aiogram import F
from aiogram.types import Message
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

ACTIONS = [
    ("💰 Set Sell Prices", "setprices"),
    ("💳 Change Balance", "changebalance"),
    ("➕ Add Number", "add"),
    ("➖ Remove Number", "remove"),
    ("🗄 Database View", "db"),
    ("📢 Broadcast", "broadcast"),
]

class AdminBalance(StatesGroup):
    waiting_change = State()

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
        if command == "changebalance":
            await state.clear()
            await state.set_state(AdminBalance.waiting_change)
            await cq.message.answer("💳 Send User ID and amount in one message:\n<code>1234567890 10 -</code> = Add ₹10\n<code>1234567890 -10</code> = Deduct ₹10\n/cancel to stop.", parse_mode="HTML")
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

    @dp.message(StateFilter(AdminBalance.waiting_change), Command("cancel"))
    async def cancel_balance(message: Message, state):
        await state.clear()
        await message.answer("❌ Change Balance cancelled.")

    @dp.message(StateFilter(AdminBalance.waiting_change))
    async def change_balance(message: Message, state):
        if not is_admin(message.from_user.id):
            await state.clear()
            return await message.answer("❌ Not authorized.")

        from decimal import Decimal, InvalidOperation
        from pymongo import ReturnDocument

        parts = (message.text or "").strip().split()
        if len(parts) not in (2, 3) or (len(parts) == 3 and parts[2] != "-"):
            return await message.answer("❌ Format: <code>1234567890 10 -</code> (add) or <code>1234567890 -10</code> (deduct)", parse_mode="HTML")
        if not parts[0].isascii() or not parts[0].isdecimal() or not (0 < int(parts[0]) < 10**16):
            return await message.answer("❌ Invalid Telegram User ID.")
        try:
            amount = Decimal(parts[1])
            if (not amount.is_finite() or amount == 0 or abs(amount) > 100000
                    or amount.as_tuple().exponent < -2 or (len(parts) == 3 and amount < 0)):
                raise InvalidOperation()
        except (InvalidOperation, ValueError):
            return await message.answer("❌ Invalid amount. Use up to ₹100000 and max 2 decimal places.")

        target = int(parts[0])
        deduct = amount < 0
        # MongoDB $inc is atomic. Deduction cannot push a wallet below zero.
        condition = {"_id": target}
        if deduct:
            condition["balance"] = {"$gte": float(-amount)}
        updated = handlers["users_col"].find_one_and_update(
            condition, {"$inc": {"balance": float(amount)}},
            return_document=ReturnDocument.AFTER
        )
        if not updated:
            return await message.answer("❌ User not found or insufficient balance.")
        await state.clear()
        action = "Deducted" if deduct else "Added"
        await message.answer(
            f"✅ Balance {action}!\n🆔 User ID: <code>{target}</code>\n"
            f"{'➖' if deduct else '➕'} {action}: ₹{abs(amount):.2f}\n"
            f"💰 New Balance: ₹{updated.get('balance', 0):.2f}",
            parse_mode="HTML"
        )
        try:
            await bot.send_message(target, f"💰 Admin {action.lower()} ₹{abs(amount):.2f} {'from' if deduct else 'to'} your wallet.")
        except Exception:
            pass
