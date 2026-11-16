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

class AdminUserLookup(StatesGroup):
    waiting_id = State()

class AdminBalance(StatesGroup):
    waiting_change = State()

class AdminBroadcast(StatesGroup):
    waiting_message = State()

def register_admin_panel(dp, bot, admin_ids, handlers):
    def is_admin(uid):
        return uid in admin_ids

    settings = handlers["users_col"].database["admin_settings"]

    def maintenance_enabled():
        return bool((settings.find_one({"_id": "maintenance"}) or {}).get("enabled", False))

    def menu():
        kb = InlineKeyboardBuilder()
        kb.button(text=("🔴 Status: Bot Under Maintenance" if maintenance_enabled() else "🟢 Status: Bot is ON"), callback_data="admin_toggle_maintenance")
        kb.button(text="➕ Add Single Acc", callback_data="admin_do:add")
        kb.button(text="📊 Manage Stock", callback_data="admin_stock_info")
        kb.button(text="💰 Set Account Prices", callback_data="admin_do:setprices")
        kb.button(text="📈 Statistics", callback_data="admin_do:db")
        kb.button(text="📢 Broadcast", callback_data="admin_do:broadcast")
        kb.button(text="👤 User Info", callback_data="admin_user_lookup")
        kb.button(text="💰 Change Balance", callback_data="admin_do:changebalance")
        kb.button(text="💳 Payments", callback_data="gw_settings")
        kb.button(text="➖ Remove Number", callback_data="admin_do:remove")
        kb.button(text="⬅️ Back to Menu", callback_data="back_main")
        kb.adjust(1, 2, 2, 2, 2, 1, 1)
        return kb.as_markup()

    @dp.callback_query(F.data == "admin_toggle_maintenance")
    async def toggle_maintenance(cq):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        new_value = not maintenance_enabled()
        settings.update_one({"_id": "maintenance"}, {"$set": {"enabled": new_value}}, upsert=True)
        await cq.message.edit_reply_markup(reply_markup=menu())
        await cq.answer("🔴 Maintenance enabled" if new_value else "🟢 Bot enabled", show_alert=True)

    @dp.callback_query(F.data == "admin_stock_info")
    async def stock_info(cq):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        await cq.message.answer("📊 Manage Stock: detailed country/category/year price editor is being built. Existing add/remove account controls are available in this dashboard.")
        await cq.answer()

    @dp.callback_query(F.data == "admin_user_lookup")
    async def user_lookup_start(cq, state):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        await state.set_state(AdminUserLookup.waiting_id)
        await cq.message.answer("👤 Send Telegram User ID to view wallet and account details. /cancel to stop.")
        await cq.answer()

    @dp.message(StateFilter(AdminUserLookup.waiting_id), Command("cancel"))
    async def cancel_user_lookup(message, state):
        await state.clear()
        await message.answer("Cancelled.")

    @dp.message(StateFilter(AdminUserLookup.waiting_id))
    async def user_lookup(message, state):
        if not is_admin(message.from_user.id):
            await state.clear()
            return
        value = (message.text or "").strip()
        if not value.isascii() or not value.isdecimal() or not 0 < int(value) < 10**16:
            return await message.answer("❌ Send a valid numeric User ID.")
        user = handlers["users_col"].find_one({"_id": int(value)})
        if not user:
            return await message.answer("❌ User not found.")
        from html import escape
        await state.clear()
        await message.answer(
            f"👤 <b>User Info</b>\\n🆔 ID: <code>{value}</code>\\n"
            f"Username: {escape(str(user.get('username') or 'Not set'))}\\n"
            f"💰 Balance: ₹{float(user.get('balance') or 0):.2f}\\n"
            f"🚫 Banned: {'Yes' if user.get('banned') else 'No'}",
            parse_mode="HTML"
        )

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
            await cq.message.answer("💳 Send User ID and amount in one message:\\n<code>1234567890 10 -</code> = Add ₹10\\n<code>1234567890 -10</code> = Deduct ₹10\\n/cancel to stop.", parse_mode="HTML")
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
            f"✅ Balance {action}!\\n🆔 User ID: <code>{target}</code>\\n"
            f"{'➖' if deduct else '➕'} {action}: ₹{abs(amount):.2f}\\n"
            f"💰 New Balance: ₹{updated.get('balance', 0):.2f}",
            parse_mode="HTML"
        )
        try:
            await bot.send_message(target, f"💰 Admin {action.lower()} ₹{abs(amount):.2f} {'from' if deduct else 'to'} your wallet.")
        except Exception:
            pass
