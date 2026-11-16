"""Telegram admin menu; reuses existing command handlers."""
from aiogram import F
from aiogram.types import Message, BufferedInputFile
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape
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

class AdminConfigInput(StatesGroup):
    waiting = State()

class PaymentMethodState(StatesGroup):
    name = State()
    qr = State()
    caption = State()

class StockPrice(StatesGroup):
    waiting_price = State()

class AdminUserLookup(StatesGroup):
    waiting_id = State()

class AdminBalance(StatesGroup):
    waiting_change = State()

class AdminBroadcast(StatesGroup):
    waiting_message = State()

def register_admin_panel(dp, bot, admin_ids, handlers):
    def is_admin(uid):
        return uid in admin_ids

    database = handlers["users_col"].database
    settings = database["admin_settings"]
    numbers = database["numbers"]
    payment_methods = database["manual_payment_methods"]

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
        kb.button(text="🎁 Discount", callback_data="adm_config:discount")
        kb.button(text="👥 Ref %", callback_data="adm_config:ref")
        kb.button(text="🔗 Support URL", callback_data="adm_config:support")
        kb.button(text="🚫 Ban / Unban", callback_data="adm_config:ban")
        kb.button(text="📈 Sales Statistics", callback_data="adm_stats")
        kb.button(text="💾 Backup Users", callback_data="adm_backup")
        kb.button(text="💳 Payments", callback_data="adm_payments")
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

    @dp.callback_query(F.data == "adm_stats")
    async def admin_statistics(cq):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        users = handlers["users_col"]
        orders = database["orders"]
        await cq.message.edit_text(
            f"📈 <b>Bot Statistics</b>\\n👥 Users: {users.count_documents({})}\\n"
            f"📦 Available stock: {numbers.count_documents({'used': False})}\\n"
            f"🧾 Purchased orders: {orders.count_documents({'status': 'purchased'})}",
            reply_markup=menu())
        await cq.answer()

    @dp.callback_query(F.data == "adm_backup")
    async def admin_backup(cq):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        users = list(handlers["users_col"].find({}))
        from bson import json_util
        payload = json_util.dumps(users, ensure_ascii=False, indent=2).encode("utf-8")
        await cq.message.edit_text(f"💾 Users backup prepared: {len(users)} records.", reply_markup=menu())
        await bot.send_document(cq.from_user.id, BufferedInputFile(payload, filename="users_backup.json"),
                                caption="🔒 Private user backup. Keep this file secure.")
        await cq.answer()

    @dp.callback_query(F.data.startswith("adm_config:"))
    async def config_start(cq, state):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        action = cq.data.partition(":")[2]
        prompts = {
            "discount": "🎁 Send: user_id discount_percent (0-100)",
            "ref": "👥 Send global referral percentage (0-100)",
            "support": "🔗 Send https://t.me/username or @username",
            "ban": "🚫 Send: user_id ban OR user_id unban"
        }
        if action not in prompts:
            return await cq.answer("Invalid action", show_alert=True)
        await state.set_state(AdminConfigInput.waiting)
        await state.update_data(config_action=action, config_chat=cq.message.chat.id,
                                config_message=cq.message.message_id)
        await cq.message.edit_text(prompts[action] + "\\n/cancel to abort.")
        await cq.answer()

    @dp.message(StateFilter(AdminConfigInput.waiting), Command("cancel"))
    async def config_cancel(message, state):
        await state.clear()
        await message.answer("Cancelled. Open /admin to continue.")

    @dp.message(StateFilter(AdminConfigInput.waiting))
    async def config_save(message, state):
        if not is_admin(message.from_user.id):
            await state.clear()
            return
        data = await state.get_data()
        action = data["config_action"]
        value = (message.text or "").strip()
        try:
            if action in ("discount", "ban"):
                uid, parameter = value.split()
                if not uid.isascii() or not uid.isdecimal() or not 0 < int(uid) < 10**16:
                    raise ValueError()
                if action == "discount":
                    pct = Decimal(parameter)
                    if not pct.is_finite() or not 0 <= pct <= 100 or pct.as_tuple().exponent < -2:
                        raise ValueError()
                    result = handlers["users_col"].update_one({"_id": int(uid)}, {"$set": {"discount_percent": float(pct)}})
                else:
                    if parameter not in ("ban", "unban"):
                        raise ValueError()
                    result = handlers["users_col"].update_one({"_id": int(uid)}, {"$set": {"banned": parameter == "ban"}})
                if not result.matched_count:
                    return await message.answer("❌ User not found.")
            elif action == "ref":
                pct = Decimal(value)
                if not pct.is_finite() or not 0 <= pct <= 100 or pct.as_tuple().exponent < -2:
                    raise ValueError()
                settings.update_one({"_id": "referral"}, {"$set": {"percent": float(pct)}}, upsert=True)
            else:
                import re
                if not re.fullmatch(r"(?:https://t\\.me/|@)[A-Za-z0-9_]{5,32}", value):
                    raise ValueError()
                settings.update_one({"_id": "support"}, {"$set": {"url": value}}, upsert=True)
        except (ValueError, InvalidOperation):
            return await message.answer("❌ Invalid input. Follow the displayed format.")
        await state.clear()
        await bot.edit_message_text(chat_id=data["config_chat"], message_id=data["config_message"],
                                    text=f"✅ {escape(action.title())} setting saved.", reply_markup=menu())
        try:
            await message.delete()
        except Exception:
            pass

    def payment_menu():
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Add Payment Method", callback_data="adm_pay_add")
        kb.button(text="🗑 Remove Payment Method", callback_data="adm_pay_remove")
        kb.button(text="🔄 Manual ON/OFF", callback_data="adm_pay_toggle")
        kb.button(text="⚡ Automatic UPI Gateway", callback_data="gw_settings")
        kb.button(text="⬅️ Back to Admin", callback_data="admin_panel")
        kb.adjust(1)
        return kb.as_markup()

    def manual_enabled():
        return (settings.find_one({"_id": "manual_payments"}) or {}).get("enabled", False)

    @dp.callback_query(F.data == "adm_payments")
    async def payment_panel(cq):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        count = payment_methods.count_documents({})
        await cq.message.edit_text(
            f"💳 <b>Manage Payment Methods</b>\\n"
            f"Manual: {'🟢 ON' if manual_enabled() else '🔴 OFF'}\\n"
            f"Configured methods: {count}\\n"
            "Automatic UPI: Existing gateway settings",
            reply_markup=payment_menu(), parse_mode="HTML")
        await cq.answer()

    @dp.callback_query(F.data == "adm_pay_toggle")
    async def payment_toggle(cq):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        new = not manual_enabled()
        settings.update_one({"_id": "manual_payments"}, {"$set": {"enabled": new}}, upsert=True)
        await payment_panel(cq)

    @dp.callback_query(F.data == "adm_pay_add")
    async def payment_add(cq, state):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        await state.set_state(PaymentMethodState.name)
        await state.update_data(pay_chat=cq.message.chat.id, pay_message=cq.message.message_id)
        await cq.message.edit_text("➕ <b>Add Payment Method</b>\\nSend payment method name (e.g. PhonePe). /cancel to stop.")
        await cq.answer()

    @dp.message(StateFilter(PaymentMethodState.name))
    async def payment_name(message, state):
        if not is_admin(message.from_user.id):
            await state.clear()
            return
        name = (message.text or "").strip()
        if not 1 <= len(name) <= 60:
            return await message.answer("Enter a name up to 60 characters.")
        await state.update_data(pay_name=name)
        await state.set_state(PaymentMethodState.qr)
        await message.answer("📸 Send QR image, or type skip.")

    @dp.message(StateFilter(PaymentMethodState.qr))
    async def payment_qr(message, state):
        if not is_admin(message.from_user.id):
            await state.clear()
            return
        if message.photo:
            qr = message.photo[-1].file_id
        elif (message.text or "").strip().lower() == "skip":
            qr = None
        else:
            return await message.answer("Send a photo or type skip.")
        await state.update_data(pay_qr=qr)
        await state.set_state(PaymentMethodState.caption)
        await message.answer("📝 Send payment instructions / UPI ID (max 500 characters).")

    @dp.message(StateFilter(PaymentMethodState.caption))
    async def payment_caption(message, state):
        if not is_admin(message.from_user.id):
            await state.clear()
            return
        caption = (message.text or "").strip()
        if not 1 <= len(caption) <= 500:
            return await message.answer("Send valid instructions (max 500 characters).")
        data = await state.get_data()
        payment_methods.insert_one({
            "name": data["pay_name"], "qr_file_id": data["pay_qr"],
            "caption": caption, "created_by": message.from_user.id
        })
        await state.clear()
        await bot.edit_message_text(
            chat_id=data["pay_chat"], message_id=data["pay_message"],
            text=f"✅ Payment Method Added: <b>{escape(data['pay_name'])}</b>",
            parse_mode="HTML", reply_markup=payment_menu())
        try:
            await message.delete()
        except Exception:
            pass

    @dp.callback_query(F.data == "adm_pay_remove")
    async def payment_remove_menu(cq):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        methods = list(payment_methods.find({}, {"name": 1}).limit(50))
        kb = InlineKeyboardBuilder()
        for method in methods:
            kb.button(text=f"🗑 {method['name']}", callback_data=f"adm_pay_del:{method['_id']}")
        kb.button(text="⬅️ Back", callback_data="adm_payments")
        kb.adjust(1)
        await cq.message.edit_text("🗑 Select method to remove:" if methods else "No manual payment methods.",
                                   reply_markup=kb.as_markup())
        await cq.answer()

    @dp.callback_query(F.data.startswith("adm_pay_del:"))
    async def payment_delete(cq):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        from bson import ObjectId
        try:
            oid = ObjectId(cq.data.partition(":")[2])
        except Exception:
            return await cq.answer("Invalid method", show_alert=True)
        method = payment_methods.find_one({"_id": oid})
        if not method:
            return await cq.answer("Already removed", show_alert=True)
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Confirm Remove", callback_data=f"adm_pay_confirm:{oid}")
        kb.button(text="❌ Cancel", callback_data="adm_pay_remove")
        kb.adjust(1)
        await cq.message.edit_text(f"Remove <b>{escape(method['name'])}</b>?", reply_markup=kb.as_markup())
        await cq.answer()

    @dp.callback_query(F.data.startswith("adm_pay_confirm:"))
    async def payment_delete_confirm(cq):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        from bson import ObjectId
        try:
            oid = ObjectId(cq.data.partition(":")[2])
        except Exception:
            return await cq.answer("Invalid method", show_alert=True)
        payment_methods.delete_one({"_id": oid})
        await cq.message.edit_text("✅ Payment Method Removed", reply_markup=payment_menu())
        await cq.answer()

    def stock_countries():
        return sorted(numbers.distinct("country", {"used": False, "country": {"$type": "string"}}))

    def stock_categories(country):
        return sorted({str(n.get("category") or "Good") for n in numbers.find(
            {"country": country, "used": False}, {"category": 1})})

    def stock_years(country, category):
        return sorted({str(n.get("year") or "Unknown") for n in numbers.find(
            {"country": country, "used": False}, {"year": 1, "category": 1})
            if str(n.get("category") or "Good") == category}, reverse=True)

    def stock_filter(country, category=None, year=None):
        query = {"country": country, "used": False}
        if category is not None:
            query["$or"] = [{"category": category}]
            if category == "Good":
                query["$or"].append({"category": {"$exists": False}})
                query["$or"].append({"category": None})
        if year is not None:
            if year == "Unknown":
                query["$and"] = [{"$or": [{"year": {"$exists": False}}, {"year": None}, {"year": ""}]}]
            else:
                query["year"] = {"$in": [year, int(year)]} if year.isdecimal() else year
        return query

    async def render_stock(cq, level=0, ci=None, ki=None, yi=None):
        countries = stock_countries()
        kb = InlineKeyboardBuilder()
        if level == 0:
            if not countries:
                text = "📊 <b>Manage Stock</b>\\nNo available accounts."
            else:
                text = "📊 <b>Manage Stock</b>\\nSelect a country:"
                for i, country in enumerate(countries):
                    count = numbers.count_documents({"country": country, "used": False})
                    kb.button(text=f"🌍 {country} ({count})", callback_data=f"stk:c:{i}")
        elif ci is None or ci >= len(countries):
            return await render_stock(cq)
        else:
            country = countries[ci]
            cats = stock_categories(country)
            if level == 1:
                text = f"🌍 <b>{escape(country)}</b>\\nSelect a category:"
                for i, cat in enumerate(cats):
                    count = numbers.count_documents(stock_filter(country, cat))
                    kb.button(text=f"{'🟢 HEALTHY' if cat == 'Good' else cat} ({count})", callback_data=f"stk:k:{ci}:{i}")
            elif ki is None or ki >= len(cats):
                return await render_stock(cq, 1, ci)
            else:
                cat = cats[ki]
                years = stock_years(country, cat)
                if level == 2:
                    text = f"🌍 {escape(country)}\\nCategory: <b>{escape(cat)}</b>\\nSelect a year:"
                    for i, year in enumerate(years):
                        count = numbers.count_documents(stock_filter(country, cat, year))
                        kb.button(text=f"📅 {year} ({count})", callback_data=f"stk:y:{ci}:{ki}:{i}")
                elif yi is None or yi >= len(years):
                    return await render_stock(cq, 2, ci, ki)
                else:
                    year = years[yi]
                    docs = list(numbers.find(stock_filter(country, cat, year), {"price": 1}))
                    prices = sorted({str(d.get("price", "Not set")) for d in docs})
                    text = (f"📊 <b>Stock Price Editor</b>\\n🌍 {escape(country)}\\n"
                            f"Category: {escape(cat)}\\n📅 Year: {escape(year)}\\n"
                            f"📦 Accounts: {len(docs)}\\n💰 Current prices: {escape(', '.join(prices[:10]))}\\n\\n"
                            "Change price for ALL available accounts in this category/year?")
                    kb.button(text="💰 Change Price", callback_data=f"stk:p:{ci}:{ki}:{yi}")
            kb.button(text="⬅️ Back", callback_data=("stk:home" if level == 1 else
                      f"stk:c:{ci}" if level == 2 else f"stk:k:{ci}:{ki}"))
        kb.button(text="🏠 Admin Panel", callback_data="admin_panel")
        kb.adjust(1)
        await cq.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

    @dp.callback_query(F.data == "admin_stock_info")
    async def stock_info(cq):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        await render_stock(cq)
        await cq.answer()

    @dp.callback_query(F.data.startswith("stk:"))
    async def stock_navigation(cq, state):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        parts = cq.data.split(":")
        action = parts[1]
        if action == "home":
            await render_stock(cq)
        elif action in {"c", "k", "y"}:
            ci = int(parts[2])
            ki = int(parts[3]) if len(parts) > 3 else None
            yi = int(parts[4]) if len(parts) > 4 else None
            await render_stock(cq, {"c": 1, "k": 2, "y": 3}[action], ci, ki, yi)
        elif action == "p":
            ci, ki, yi = map(int, parts[2:5])
            countries = stock_countries()
            if ci >= len(countries):
                return await cq.answer("Stock changed; reopen menu", show_alert=True)
            cats = stock_categories(countries[ci])
            if ki >= len(cats):
                return await cq.answer("Stock changed; reopen menu", show_alert=True)
            years = stock_years(countries[ci], cats[ki])
            if yi >= len(years):
                return await cq.answer("Stock changed; reopen menu", show_alert=True)
            await state.set_state(StockPrice.waiting_price)
            await state.update_data(stock_country=countries[ci], stock_category=cats[ki],
                                    stock_year=years[yi], stock_message_id=cq.message.message_id,
                                    stock_chat_id=cq.message.chat.id)
            await cq.message.edit_text(
                f"💰 Enter new INR price for {escape(countries[ci])} / {escape(cats[ki])} / {escape(years[yi])}.\\n"
                "All matching AVAILABLE accounts will be updated.\\nSend /cancel to abort.")
        await cq.answer()

    @dp.message(StateFilter(StockPrice.waiting_price), Command("cancel"))
    async def stock_cancel(message, state):
        await state.clear()
        await message.answer("❌ Price edit cancelled. Open Admin Panel to continue.")

    @dp.message(StateFilter(StockPrice.waiting_price))
    async def stock_save_price(message, state):
        if not is_admin(message.from_user.id):
            await state.clear()
            return
        try:
            price = Decimal((message.text or "").strip())
            if not price.is_finite() or price <= 0 or price > 100000 or price.as_tuple().exponent < -2:
                raise InvalidOperation()
        except (InvalidOperation, ValueError):
            return await message.answer("❌ Enter a valid INR amount (0.01 to 100000, max 2 decimals).")
        data = await state.get_data()
        query = stock_filter(data["stock_country"], data["stock_category"], data["stock_year"])
        result = numbers.update_many(query, {"$set": {"price": float(price)}})
        await state.clear()
        await bot.edit_message_text(
            chat_id=data["stock_chat_id"], message_id=data["stock_message_id"],
            text=(f"✅ <b>Stock Price Updated</b>\\n🌍 {escape(data['stock_country'])}\\n"
                  f"Category: {escape(data['stock_category'])}\\n📅 Year: {escape(data['stock_year'])}\\n"
                  f"💰 New price: ₹{price:.2f}\\n📦 Updated accounts: {result.modified_count}"),
            reply_markup=menu(), parse_mode="HTML")
        await message.delete()

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
        await cq.message.edit_text("🛡 <b>Advanced Admin Dashboard</b>", reply_markup=menu())
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

    @dp.message(StateFilter(PaymentMethodState), Command("cancel"))
    async def cancel_payment_setup(message, state):
        await state.clear()
        await message.answer("Payment method setup cancelled.")

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
