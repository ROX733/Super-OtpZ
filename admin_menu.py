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
from admin_access import authorized, callback_permission

ACTIONS = [
    ("💰 Set Sell Prices", "setprices"),
    ("💳 Change Balance", "changebalance"),
    ("➕ Add Number", "add"),
    ("➖ Remove Number", "remove"),
    ("🗄 Database View", "db"),
    ("📢 Broadcast", "broadcast"),
]

class SetBio(StatesGroup):
    waiting = State()

class ManageAdmins(StatesGroup):
    waiting = State()

class ZipInventory(StatesGroup):
    upload = State()
    year = State()
    price = State()
    confirm = State()

class RestoreUsers(StatesGroup):
    document = State()

class AdminConfigInput(StatesGroup):
    waiting = State()

class PaymentMethodState(StatesGroup):
    name = State()
    qr = State()
    caption = State()

class SingleStockPrice(StatesGroup):
    waiting = State()

class StockPrice(StatesGroup):
    waiting_price = State()

class AdminUserLookup(StatesGroup):
    waiting_id = State()

class AdminBalance(StatesGroup):
    waiting_change = State()

class AdminBroadcast(StatesGroup):
    waiting_message = State()

def register_admin_panel(dp, bot, admin_ids, handlers):
    admin_registry = handlers["users_col"].database["subadmins"]
    def is_admin(uid, permission=None):
        return authorized(uid, admin_ids, admin_registry, permission)

    def permission_for(action):
        return callback_permission(action)

    class AdminPermissionMiddleware:
        async def __call__(self, handler, event, data):
            callback = data.get("event_callback_query") or getattr(event, "callback_query", None)
            if callback:
                action = callback.data or ""
                protected = (action.startswith(("adm_", "stk:", "admin_do:", "admin_stock_info",
                    "admin_user_lookup", "admin_toggle_maintenance", "admin_panel")))
                if protected and not is_admin(callback.from_user.id, permission_for(action)):
                    await callback.answer("❌ Permission denied.", show_alert=True)
                    return
            return await handler(event, data)

    from aiogram import BaseMiddleware
    dp.update.middleware(AdminPermissionMiddleware())

    database = handlers["users_col"].database
    settings = database["admin_settings"]
    numbers = database["numbers"]
    payment_methods = database["manual_payment_methods"]

    def maintenance_enabled():
        return bool((settings.find_one({"_id": "maintenance"}) or {}).get("enabled", False))

    def menu(uid=None):
        kb = InlineKeyboardBuilder()
        actions = [
            ("🔴 Status: Bot Under Maintenance" if maintenance_enabled() else "🟢 Status: Bot is ON", "admin_toggle_maintenance"),
            ("➕ Add Single Acc", "admin_do:add"),
            ("📦 Add Session (ZIP)", "adm_zip_start"),
            ("📊 Manage Stock", "admin_stock_info"),
            ("💰 Set Account Prices", "admin_do:setprices"),
            ("📈 Statistics", "adm_stats"),
            ("📢 Broadcast", "admin_do:broadcast"),
            ("👤 User Info", "admin_user_lookup"),
            ("💰 Change Balance", "admin_do:changebalance"),
            ("🎁 Discount", "adm_config:discount"),
            ("👥 Ref %", "adm_config:ref"),
            ("🔗 Support URL", "adm_config:support"),
            ("🚫 Ban / Unban", "adm_config:ban"),
            ("💾 Backup Users", "adm_backup"),
            ("🔄 Restore Users", "adm_restore"),
            ("📝 Set Bio", "adm_setbio"),
            ("💳 Payments", "adm_payments"),
            ("🧾 Pending Deposits", "adm_pending"),
            ("👑 Manage Admins", "adm_admins"),
        ]
        visible = []
        for label, action in actions:
            if uid in admin_ids or (uid is not None and action not in ("adm_admins", "adm_setbio") and is_admin(uid, permission_for(action))):
                if action == "adm_admins":
                    continue  # Owner-only button gets its own final row.
                kb.button(text=label, callback_data=action)
                visible.append(action)
        if uid in admin_ids:
            kb.button(text="👑 Manage Admins", callback_data="adm_admins")
        kb.button(text="⬅️ Back to Menu", callback_data="back_main")
        # Mixed layout, with Manage Admins and Back each full-width at bottom.
        pattern = [1, 2, 2, 1, 2, 2, 2, 1, 2, 2, 1, 2, 2]
        widths = []
        remaining = len(visible)
        for width in pattern:
            if remaining <= 0:
                break
            take = min(width, remaining)
            widths.append(take)
            remaining -= take
        while remaining > 0:
            take = min(2, remaining)
            widths.append(take)
            remaining -= take
        if uid in admin_ids:
            widths.append(1)  # Manage Admins
        widths.append(1)  # Back to Menu
        kb.adjust(*widths)
        return kb.as_markup()

    @dp.callback_query(F.data == "admin_toggle_maintenance")
    async def toggle_maintenance(cq):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        new_value = not maintenance_enabled()
        settings.update_one({"_id": "maintenance"}, {"$set": {"enabled": new_value}}, upsert=True)
        await cq.message.edit_reply_markup(reply_markup=menu(cq.from_user.id))
        await cq.answer("🔴 Maintenance enabled" if new_value else "🟢 Bot enabled", show_alert=True)

    @dp.callback_query(F.data == "adm_setbio")
    async def bio_start(cq, state):
        if cq.from_user.id not in admin_ids:
            return await cq.answer("Owner only", show_alert=True)
        await state.set_state(SetBio.waiting)
        await state.update_data(bio_step="target")
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Cancel", callback_data="adm_bio_cancel")
        await cq.message.edit_text(
            "📱 📝 <b>Set Bio</b>\n\n"
            "Enter phone number to set bio\n"
            "Type <code>all</code> to set bio for ALL accounts in stock.\n\n"
            "Type /cancel to cancel.",
            reply_markup=kb.as_markup(), parse_mode="HTML")
        await cq.answer()

    @dp.callback_query(F.data == "adm_bio_cancel")
    async def bio_cancel_button(cq, state):
        if cq.from_user.id not in admin_ids:
            return await cq.answer("Owner only", show_alert=True)
        await state.clear()
        await cq.message.edit_text("❌ <b>Set Bio cancelled.</b>",
                                   reply_markup=menu(cq.from_user.id), parse_mode="HTML")
        await cq.answer()

    @dp.message(StateFilter(SetBio.waiting), Command("cancel"))
    async def bio_cancel(message, state):
        await state.clear()
        await message.answer("❌ Set Bio cancelled.")

    @dp.message(StateFilter(SetBio.waiting))
    async def bio_apply(message, state):
        if message.from_user.id not in admin_ids or message.chat.type != "private":
            await state.clear()
            return
        import re
        data = await state.get_data()
        step = data.get("bio_step", "target")
        value = (message.text or "").strip()
        if step == "target":
            if value.lower() != "all" and not re.fullmatch(r"\\+?[0-9]{8,15}", value):
                return await message.answer("❌ Enter a valid phone number or <code>all</code>.", parse_mode="HTML")
            await state.update_data(bio_step="text", bio_target=value.lower() if value.lower() == "all" else value.lstrip("+"))
            await message.answer(
                "📃 <b>Enter the bio text:</b>\n"
                "(Max 70 characters for Telegram bio)\n"
                "Type /cancel to cancel.", parse_mode="HTML")
            return
        if step != "text":
            await state.clear()
            return await message.answer("❌ Set Bio expired. Please start again.")
        if not 1 <= len(value) <= 70:
            return await message.answer("❌ Bio must contain 1–70 characters.")
        target = data.get("bio_target")
        if target == "all":
            records = list(numbers.find({"used": False}, {"_id": 1, "number": 1}))
        else:
            records = list(numbers.find({"number": {"$in": [target, "+" + target]}},
                                        {"_id": 1, "number": 1}).limit(1))
        await state.clear()
        total = len(records)
        if not total:
            return await message.answer("❌ No matching accounts found in stock.")
        await message.answer(f"⏳ Saving bio text for {total} stock records...")
        success = failed = 0
        for record in records:
            phone = escape(str(record.get("number") or "Unknown"))
            try:
                result = numbers.update_one({"_id": record["_id"]}, {"$set": {"bio": value}})
                if result.matched_count != 1:
                    raise ValueError("Account not found")
                success += 1
                await message.answer(
                    f"✅ Bio saved for <code>{phone}</code>:\n\n{escape(value)}",
                    parse_mode="HTML")
            except Exception:
                failed += 1
                await message.answer(f"❌ Bio save failed for <code>{phone}</code>.", parse_mode="HTML")
        await message.answer(
            "✅ <b>Bio Text Save Complete!</b>\n"
            f"✅ Success: <code>{success}</code>\n"
            f"❌ Failed: <code>{failed}</code>\n"
            f"📊 Total: <code>{total}</code>\n\n"
            "ℹ️ Saved in stock records only. Telegram profile bios were not changed.",
            parse_mode="HTML")

    # Metadata-only ZIP inventory: never extract or retain Telegram session credentials.
    @dp.callback_query(F.data == "adm_zip_start")
    async def zip_inventory_start(cq, state):
        if not is_admin(cq.from_user.id, "stock"):
            return await cq.answer("Not authorized", show_alert=True)
        if cq.message.chat.type != "private":
            return await cq.answer("Use this in private chat.", show_alert=True)
        await state.set_state(ZipInventory.upload)
        await cq.message.answer(
            "📦 <b>Add Session (ZIP)</b>\n\n"
            "Upload one <code>.zip</code> file (max 10 MB).\n"
            "Only filenames will be inspected; login sessions are not accessed or stored.\n\n"
            "Send <i>/cancel</i> to abort.", parse_mode="HTML")
        await cq.answer()

    @dp.message(StateFilter(ZipInventory.upload, ZipInventory.year, ZipInventory.price, ZipInventory.confirm), Command("cancel"))
    async def zip_inventory_cancel(message, state):
        await state.clear()
        await message.answer("❌ <b>ZIP import cancelled.</b>", parse_mode="HTML")

    @dp.message(StateFilter(ZipInventory.upload))
    async def zip_inventory_upload(message, state):
        if not is_admin(message.from_user.id, "stock") or message.chat.type != "private":
            await state.clear()
            return
        doc = message.document
        if not doc or not (doc.file_name or "").lower().endswith(".zip") or not doc.file_size or doc.file_size > 10_000_000:
            return await message.answer("❌ Upload a <b>.zip</b> file under 10 MB.", parse_mode="HTML")
        from io import BytesIO
        from zipfile import ZipFile, BadZipFile
        from hashlib import sha256
        stream = BytesIO()
        await bot.download(doc, destination=stream)
        try:
            with ZipFile(stream) as archive:
                entries = archive.infolist()
                if len(entries) > 5000:
                    raise ValueError("Too many entries")
                names = [entry.filename for entry in entries if not entry.is_dir()
                         and entry.filename.lower().endswith(".session")]
                if not names:
                    raise ValueError("No session filenames")
                # Hash names only; neither extract nor read session contents.
                keys = [sha256(name.rsplit("/", 1)[-1].casefold().encode()).hexdigest()
                        for name in names]
                keys = list(dict.fromkeys(keys))
        except (BadZipFile, ValueError, OSError):
            return await message.answer("❌ Invalid ZIP or no .session filenames found.")
        await state.update_data(zip_keys=keys, zip_total=len(names))
        kb = InlineKeyboardBuilder()
        for label, value in [("🟢 Spam Free", "Good"), ("🟠 Temporary Spam", "Temporary Spam"),
                             ("🔴 Permanent Spam", "Permanent Spam")]:
            kb.button(text=label, callback_data="adm_zip_spam:" + {"Good":"good","Temporary Spam":"temp","Permanent Spam":"perm"}[value])
        kb.adjust(1)
        await message.answer(
            f"✅ <b>ZIP scanned</b>\n\n📄 <b>Session filenames:</b> <code>{len(names)}</code>\n"
            f"🔁 <b>Unique filenames:</b> <code>{len(keys)}</code>\n"
            "🔒 <b>Live login validation:</b> Not performed\n\n"
            "<b>Select Spam Status:</b>", reply_markup=kb.as_markup(), parse_mode="HTML")

    @dp.callback_query(F.data.startswith("adm_zip_spam:"))
    async def zip_inventory_spam(cq, state):
        if not is_admin(cq.from_user.id, "stock"):
            return await cq.answer("Not authorized", show_alert=True)
        data = await state.get_data()
        if not data.get("zip_keys"):
            return await cq.answer("Upload a ZIP first.", show_alert=True)
        categories = {"good": "Good", "temp": "Temporary Spam", "perm": "Permanent Spam"}
        category = categories.get(cq.data.partition(":")[2])
        if not category:
            return await cq.answer("Invalid category.", show_alert=True)
        await state.update_data(zip_category=category)
        await state.set_state(ZipInventory.year)
        await cq.message.answer("📅 <b>Account Year</b>\n\nSend a year, e.g. <code>2024</code>.", parse_mode="HTML")
        await cq.answer()

    @dp.message(StateFilter(ZipInventory.year))
    async def zip_inventory_year(message, state):
        if not is_admin(message.from_user.id, "stock"):
            await state.clear()
            return
        raw = (message.text or "").strip()
        if not raw.isascii() or not raw.isdecimal() or not 2000 <= int(raw) <= 2100:
            return await message.answer("❌ Enter a valid year (2000–2100).")
        await state.update_data(zip_year=int(raw))
        await state.set_state(ZipInventory.price)
        await message.answer("💰 <b>Price per entry</b>\n\nSend INR amount, e.g. <code>22</code>.", parse_mode="HTML")

    @dp.message(StateFilter(ZipInventory.price))
    async def zip_inventory_price(message, state):
        if not is_admin(message.from_user.id, "stock"):
            await state.clear()
            return
        try:
            amount = Decimal((message.text or "").strip())
            if not amount.is_finite() or not Decimal("0") < amount <= Decimal("100000") or amount.as_tuple().exponent < -2:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            return await message.answer("❌ Enter a valid price (₹0.01–₹100000).")
        await state.update_data(zip_price=str(amount))
        await state.set_state(ZipInventory.confirm)
        data = await state.get_data()
        kb = InlineKeyboardBuilder()
        kb.button(text="🔒 2FA Enabled", callback_data="adm_zip_2fa:yes")
        kb.button(text="🔓 2FA Disabled", callback_data="adm_zip_2fa:no")
        kb.adjust(1)
        await message.answer("🔐 <b>2FA Status</b>\n\nSelect status (no password is collected).",
                             reply_markup=kb.as_markup(), parse_mode="HTML")

    @dp.callback_query(F.data.startswith("adm_zip_2fa:"))
    async def zip_inventory_2fa(cq, state):
        if not is_admin(cq.from_user.id, "stock"):
            return await cq.answer("Not authorized", show_alert=True)
        data = await state.get_data()
        if not data.get("zip_keys") or "zip_price" not in data:
            return await cq.answer("Start ZIP import first.", show_alert=True)
        enabled = cq.data.endswith(":yes")
        await state.update_data(zip_2fa=enabled)
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Confirm Import", callback_data="adm_zip_confirm")
        kb.button(text="❌ Cancel", callback_data="adm_zip_cancel")
        kb.adjust(1)
        await cq.message.answer(
            "📋 <b>ZIP Inventory Summary</b>\n\n"
            f"📦 <b>Unique entries:</b> <code>{len(data['zip_keys'])}</code>\n"
            f"🚫 <b>Spam Status:</b> {escape(data['zip_category'])}\n"
            f"📅 <b>Year:</b> <code>{data['zip_year']}</code>\n"
            f"💰 <b>Price:</b> ₹{data['zip_price']}\n"
            f"🔐 <b>2FA:</b> {'Enabled' if enabled else 'Disabled'}\n\n"
            "ℹ️ <i>Metadata inventory only; no session files are stored.</i>",
            reply_markup=kb.as_markup(), parse_mode="HTML")
        await cq.answer()

    @dp.callback_query(F.data == "adm_zip_cancel")
    async def zip_inventory_cancel_button(cq, state):
        if not is_admin(cq.from_user.id, "stock"):
            return await cq.answer("Not authorized", show_alert=True)
        await state.clear()
        await cq.message.edit_text("❌ <b>ZIP import cancelled.</b>", parse_mode="HTML")
        await cq.answer()

    @dp.callback_query(F.data == "adm_zip_confirm")
    async def zip_inventory_confirm(cq, state):
        if not is_admin(cq.from_user.id, "stock"):
            return await cq.answer("Not authorized", show_alert=True)
        if await state.get_state() != ZipInventory.confirm.state:
            return await cq.answer("Import session expired.", show_alert=True)
        data = await state.get_data()
        if not data.get("zip_keys") or "zip_2fa" not in data:
            return await cq.answer("Complete the import first.", show_alert=True)
        from pymongo import UpdateOne
        inventory = database["zip_session_metadata"]
        operations = [UpdateOne({"_id": key}, {"$setOnInsert": {
            "category": data["zip_category"], "status": data["zip_category"],
            "year": data["zip_year"], "price": data["zip_price"],
            "two_factor_enabled": data["zip_2fa"], "created_at": datetime.now(timezone.utc)}},
            upsert=True) for key in data["zip_keys"]]
        result = inventory.bulk_write(operations, ordered=False)
        await state.clear()
        await cq.message.edit_text(
            "✅ <b>ZIP Metadata Import Complete</b>\n\n"
            f"➕ <b>Added:</b> <code>{result.upserted_count}</code>\n"
            f"⏭ <b>Duplicates:</b> <code>{len(operations)-result.upserted_count}</code>\n"
            "🔒 <b>Session credentials stored:</b> No",
            parse_mode="HTML")
        await cq.answer()

    ADMIN_GROUPS = {
        "add": ("Add Stock", ("accounts",)),
        "manage": ("Manage Stock", ("stock",)),
        "stats": ("Stats & Bcast", ("stats", "broadcast")),
        "users": ("Bal & Users", ("users", "payments")),
        "settings": ("Settings", ("settings", "backup")),
    }

    def admin_manage_keyboard():
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Add Admin", callback_data="adm_admin_add")
        kb.button(text="✏️ Edit Admin", callback_data="adm_admin_edit")
        kb.button(text="⬅️ Back", callback_data="admin_panel")
        kb.adjust(2, 1)
        return kb.as_markup()

    def admin_permissions_keyboard(uid, permissions):
        kb = InlineKeyboardBuilder()
        for key, (label, perms) in ADMIN_GROUPS.items():
            enabled = all(p in permissions for p in perms)
            kb.button(text=f"{label}: {'✅' if enabled else '❌'}",
                      callback_data=f"adm_admin_toggle:{uid}:{key}")
        kb.button(text="🗑 Remove Admin", callback_data=f"adm_admin_delete:{uid}")
        kb.button(text="⬅️ Back", callback_data="adm_admins")
        kb.adjust(1)
        return kb.as_markup()

    @dp.callback_query(F.data == "adm_admins")
    async def manage_admins(cq):
        if cq.from_user.id not in admin_ids:
            return await cq.answer("Owner only", show_alert=True)
        entries = list(admin_registry.find({"active": True}, {"_id": 1}).sort("_id", 1).limit(50))
        lines = ["👥 <b>Manage Sub-Admins</b>", ""]
        lines.extend(f"👤 <code>{entry['_id']}</code>" for entry in entries)
        if not entries:
            lines.append("No active sub-admins.")
        lines.append("\n🔒 Owner IDs cannot be edited or removed.")
        await cq.message.edit_text("\n".join(lines), reply_markup=admin_manage_keyboard(), parse_mode="HTML")
        await cq.answer()

    @dp.callback_query(F.data.in_({"adm_admin_add", "adm_admin_edit"}))
    async def admin_edit_start(cq, state):
        if cq.from_user.id not in admin_ids:
            return await cq.answer("Owner only", show_alert=True)
        mode = "add" if cq.data == "adm_admin_add" else "edit"
        await state.set_state(ManageAdmins.waiting)
        await state.update_data(admin_mode=mode)
        await cq.message.answer(
            "👤 <b>Enter User ID for new Admin:</b>" if mode == "add"
            else "✏️ <b>Enter User ID to edit Admin:</b>\n\nSend /cancel to abort.",
            parse_mode="HTML")
        await cq.answer()

    @dp.message(StateFilter(ManageAdmins.waiting), Command("cancel"))
    async def admin_edit_cancel(message, state):
        await state.clear()
        await message.answer("❌ Cancelled.")

    @dp.message(StateFilter(ManageAdmins.waiting))
    async def admin_edit_save(message, state):
        if message.from_user.id not in admin_ids or message.chat.type != "private":
            await state.clear()
            return
        raw = (message.text or "").strip()
        if not raw.isascii() or not raw.isdecimal() or not 0 < int(raw) < 10**16:
            return await message.answer("❌ Enter a valid numeric User ID.")
        uid = int(raw)
        if uid in admin_ids:
            return await message.answer("🔒 Owner IDs cannot be edited.")
        data = await state.get_data()
        mode = data.get("admin_mode")
        if mode == "add":
            existing = admin_registry.find_one({"_id": uid, "active": True})
            if existing:
                return await message.answer("ℹ️ Already a sub-admin. Use Edit Admin.")
            admin_registry.update_one({"_id": uid},
                {"$set": {"active": True, "permissions": []}}, upsert=True)
            await message.answer("✅ Admin added!")
        elif mode == "edit":
            if not admin_registry.find_one({"_id": uid, "active": True}):
                return await message.answer("❌ Active sub-admin not found.")
        else:
            await state.clear()
            return await message.answer("❌ Start again from Manage Admins.")
        await state.clear()
        record = admin_registry.find_one({"_id": uid, "active": True})
        await message.answer(
            f"✏️ <b>Editing Admin:</b> <code>{uid}</code>",
            reply_markup=admin_permissions_keyboard(uid, record.get("permissions", [])),
            parse_mode="HTML")

    @dp.callback_query(F.data.startswith("adm_admin_toggle:"))
    async def admin_permission_toggle(cq):
        if cq.from_user.id not in admin_ids:
            return await cq.answer("Owner only", show_alert=True)
        try:
            _, raw_uid, group = cq.data.split(":", 2)
            uid = int(raw_uid)
        except (ValueError, TypeError):
            return await cq.answer("Invalid action", show_alert=True)
        if uid in admin_ids or group not in ADMIN_GROUPS:
            return await cq.answer("Protected or invalid action", show_alert=True)
        record = admin_registry.find_one({"_id": uid, "active": True})
        if not record:
            return await cq.answer("Admin no longer active", show_alert=True)
        current = set(record.get("permissions", []))
        perms = set(ADMIN_GROUPS[group][1])
        updated = (current - perms) if perms.issubset(current) else (current | perms)
        admin_registry.update_one({"_id": uid, "active": True},
                                  {"$set": {"permissions": sorted(updated)}})
        await cq.message.edit_reply_markup(reply_markup=admin_permissions_keyboard(uid, updated))
        await cq.answer("Permission updated")

    @dp.callback_query(F.data.startswith("adm_admin_delete:"))
    async def admin_delete(cq):
        if cq.from_user.id not in admin_ids:
            return await cq.answer("Owner only", show_alert=True)
        try:
            uid = int(cq.data.rsplit(":", 1)[1])
        except ValueError:
            return await cq.answer("Invalid User ID", show_alert=True)
        if uid in admin_ids:
            return await cq.answer("Owner IDs are protected", show_alert=True)
        result = admin_registry.update_one({"_id": uid, "active": True},
                                           {"$set": {"active": False}})
        if not result.matched_count:
            return await cq.answer("Admin already removed", show_alert=True)
        await cq.message.edit_text(f"✅ Admin <code>{uid}</code> removed.",
                                   reply_markup=admin_manage_keyboard(), parse_mode="HTML")
        await cq.answer()

    @dp.callback_query(F.data == "adm_stats")
    async def admin_statistics(cq):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        from decimal import Decimal
        users = handlers["users_col"]
        orders = database["orders"]
        available = numbers.count_documents({"used": False})
        categories = {}
        for doc in numbers.aggregate([
            {"$match": {"used": False}},
            {"$group": {"_id": "$category", "count": {"$sum": 1}}}
        ]):
            name = str(doc["_id"] or "Good")
            categories[name] = categories.get(name, 0) + doc["count"]
        category_text = " / ".join(
            f"{escape(name)} {count}" for name, count in sorted(categories.items())
        )
        stock_line = f"📦 <b>Accounts in Stock:</b> <code>{available}</code>"
        if category_text:
            stock_line += f" ({category_text})"
        balance_result = list(users.aggregate([
            {"$group": {"_id": None, "total": {"$sum": "$balance"}}}
        ]))
        total_balance = balance_result[0]["total"] if balance_result else 0
        sales_result = list(orders.aggregate([
            {"$match": {"status": "purchased"}},
            {"$group": {"_id": None, "count": {"$sum": 1}, "total": {"$sum": "$price"}}}
        ]))
        sold = sales_result[0]["count"] if sales_result else 0
        sales_amount = sales_result[0]["total"] if sales_result else 0
        paid = database["gateway_payments"].find({"status": "paid"}, {"amount": 1})
        upi_revenue = sum((Decimal(str(p.get("amount") or 0)) for p in paid), Decimal("0"))
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Back", callback_data="admin_panel")
        await cq.message.edit_text(
            "📊 <b>ADVANCED STATS</b>\n\n"
            f"👥 <b>Total Users:</b> <code>{users.count_documents({})}</code>\n"
            f"{stock_line}\n"
            f"💰 <b>Total UPI Revenue:</b> ₹{upi_revenue:g}\n\n"
            f"💳 <b>Overall Users Balance:</b> ₹{total_balance:g}\n"
            f"🛒 <b>Total Accounts Sold:</b> <code>{sold}</code>\n"
            f"💵 <b>Overall Sales Amount:</b> ₹{sales_amount:g}",
            reply_markup=kb.as_markup(), parse_mode="HTML")
        await cq.answer()

    @dp.callback_query(F.data == "adm_backup")
    async def admin_backup(cq):
        if not is_admin(cq.from_user.id, "backup"):
            return await cq.answer("Not authorized", show_alert=True)
        import csv
        from io import StringIO
        from bson import json_util
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["user_id", "user_data_json"])
        count = 0
        for user in handlers["users_col"].find({}):
            writer.writerow([user["_id"], json_util.dumps(user, ensure_ascii=False)])
            count += 1
        payload = output.getvalue().encode("utf-8-sig")
        await bot.send_document(
            cq.from_user.id, BufferedInputFile(payload, filename="users_backup.csv"),
            caption="👥 <b>Users Backup CSV</b>", parse_mode="HTML")
        await cq.answer()

    @dp.callback_query(F.data == "adm_restore")
    async def restore_start(cq, state):
        if not is_admin(cq.from_user.id, "backup"):
            return await cq.answer("Not authorized", show_alert=True)
        if cq.message.chat.type != "private":
            return await cq.answer("Restore is available in private chat only.", show_alert=True)
        await state.set_state(RestoreUsers.document)
        await cq.message.answer(
            "📤 <b>Send the <code>users_backup.csv</code> file:</b>\n\n"
            "Send <i>/cancel</i> only if you want to abort.",
            parse_mode="HTML")
        await cq.answer()

    @dp.message(StateFilter(RestoreUsers.document), Command("cancel"))
    async def restore_cancel(message, state):
        await state.clear()
        await message.answer("❌ <b>Cancelled.</b>", parse_mode="HTML")

    @dp.message(StateFilter(RestoreUsers.document))
    async def restore_document(message, state):
        if not is_admin(message.from_user.id, "backup") or message.chat.type != "private":
            await state.clear()
            return
        doc = message.document
        if not doc or not (doc.file_name or "").lower().endswith(".csv") or not doc.file_size or doc.file_size > 10_000_000:
            return await message.answer("❌ Upload a CSV backup under 10 MB.")
        import csv
        from io import BytesIO, StringIO
        from bson import json_util
        from pymongo import UpdateOne
        stream = BytesIO()
        await bot.download(doc, destination=stream)
        try:
            decoded = stream.getvalue().decode("utf-8-sig")
            reader = csv.DictReader(StringIO(decoded))
            if reader.fieldnames != ["user_id", "user_data_json"]:
                raise ValueError("Invalid backup headers")
            operations = []
            seen = set()
            protected = {
                "credited_manual_deposits", "credited_gateway_orders",
                "credited_referral_deposits", "credited_referral_gateway_orders"
            }
            for row in reader:
                if len(operations) >= 100000 or None in row or any(v is None for v in row.values()):
                    raise ValueError("Malformed CSV")
                uid_text = row["user_id"]
                if not uid_text.isascii() or not uid_text.isdecimal():
                    raise ValueError("Invalid ID")
                uid = int(uid_text)
                if uid <= 0 or uid in seen:
                    raise ValueError("Duplicate/invalid ID")
                seen.add(uid)
                entry = json_util.loads(row["user_data_json"])
                if not isinstance(entry, dict) or type(entry.get("_id")) is not int or entry["_id"] != uid:
                    raise ValueError("Invalid user record")
                clean = {k: v for k, v in entry.items() if k != "_id" and k not in protected}
                operations.append(UpdateOne({"_id": uid}, {"$set": clean}, upsert=True))
            if not operations:
                raise ValueError("Empty backup")
        except (ValueError, UnicodeError, TypeError, KeyError, csv.Error):
            return await message.answer("❌ <b>Invalid backup CSV.</b> Nothing restored.", parse_mode="HTML")
        try:
            handlers["users_col"].bulk_write(operations, ordered=False)
        except Exception:
            return await message.answer("❌ <b>Restore failed.</b> Some records may have been updated; check the database before retrying.", parse_mode="HTML")
        await state.clear()
        await message.answer(f"✅ <b>Restored <code>{len(operations)}</code> users.</b>", parse_mode="HTML")

    @dp.callback_query(F.data.startswith("adm_config:"))
    async def config_start(cq, state):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        action = cq.data.partition(":")[2]
        prompts = {
            "discount": "👤 <b>User ID:</b>\n\nSend <i>/cancel</i> only if you want to abort.",
            "ref": "👥 <b>New Referral %:</b>\n\nSend <i>/cancel</i> only if you want to abort.",
            "support": "🔗 <b>Enter new Support URL (HTTPS URL or <code>@username</code>):</b>\n\nSend <i>/cancel</i> only if you want to abort.",
            "ban": "🚫 <b>Ban / Unban User</b>\n\nSend User ID and action:\n<code>123456789 ban</code>\n<code>123456789 unban</code>\n\nSend <i>/cancel</i> only if you want to abort."
        }
        if action not in prompts:
            return await cq.answer("Invalid action", show_alert=True)
        await state.set_state(AdminConfigInput.waiting)
        await state.update_data(config_action=action, config_chat=cq.message.chat.id,
                                config_message=None)
        sent = await cq.message.answer(prompts[action], parse_mode="HTML")
        await state.update_data(config_message=sent.message_id)
        await cq.answer()

    @dp.message(StateFilter(AdminConfigInput.waiting), Command("cancel"))
    async def config_cancel(message, state):
        await state.clear()
        await message.answer("Cancelled. Open /admin to continue.")

    @dp.message(StateFilter(AdminConfigInput.waiting))
    async def config_save(message, state):
        cfg = (await state.get_data()).get("config_action")
        needed = "users" if cfg in ("ban", "discount") else "settings"
        if not is_admin(message.from_user.id, needed):
            await state.clear()
            return
        data = await state.get_data()
        action = data["config_action"]
        value = (message.text or "").strip()
        if action == "discount":
            if not data.get("discount_user_id"):
                if not value.isascii() or not value.isdecimal() or not 0 < int(value) < 10**16:
                    return await message.answer("❌ <b>Invalid User ID.</b> Send a numeric Telegram User ID.", parse_mode="HTML")
                if not handlers["users_col"].find_one({"_id": int(value)}, {"_id": 1}):
                    return await message.answer("❌ <b>User not found.</b> Send another User ID.", parse_mode="HTML")
                await state.update_data(discount_user_id=int(value))
                return await message.answer(
                    "🎁 <b>Discount %</b> (0 to remove):\n\n"
                    "Send <code>10</code> for 10% discount.\n"
                    "Send <i>/cancel</i> only if you want to abort.",
                    parse_mode="HTML")
            try:
                pct = Decimal(value)
                if not pct.is_finite() or not 0 <= pct <= 100 or pct.as_tuple().exponent < -2:
                    raise ValueError()
            except (ValueError, InvalidOperation):
                return await message.answer("❌ <b>Invalid discount.</b> Send a number from <code>0</code> to <code>100</code>.", parse_mode="HTML")
            uid = data["discount_user_id"]
            result = handlers["users_col"].update_one(
                {"_id": uid}, {"$set": {"discount_percent": float(pct)}})
            if not result.matched_count:
                await state.clear()
                return await message.answer("❌ User not found.")
            await state.clear()
            await message.answer(
                f"✅ <b>User <code>{uid}</code> has {pct:g}% discount.</b>",
                parse_mode="HTML")
            return
        try:
            if action == "ban":
                parts = value.split()
                if len(parts) != 2:
                    raise ValueError()
                uid_text, parameter = parts
                parameter = parameter.lower()
                if (not uid_text.isascii() or not uid_text.isdecimal()
                        or not 0 < int(uid_text) < 10**16
                        or parameter not in ("ban", "unban")):
                    raise ValueError()
                target_uid = int(uid_text)
                if target_uid == message.from_user.id:
                    return await message.answer(
                        "❌ <b>You cannot ban or unban yourself.</b>", parse_mode="HTML")
                if is_admin(target_uid):
                    return await message.answer(
                        "🛡 <b>Protected account.</b> Admins and the owner cannot be banned or unbanned here.",
                        parse_mode="HTML")
                target = handlers["users_col"].find_one({"_id": target_uid}, {"banned": 1})
                if target is None:
                    return await message.answer(
                        f"❌ <b>User <code>{target_uid}</code> not found.</b>", parse_mode="HTML")
                requested_ban = parameter == "ban"
                if bool(target.get("banned", False)) == requested_ban:
                    return await message.answer(
                        f"ℹ️ User <code>{target_uid}</code> is already "
                        f"{'banned' if requested_ban else 'unbanned'}.",
                        parse_mode="HTML")
                # Recheck admin status immediately before writing; do not rely on UI checks.
                if is_admin(target_uid):
                    return await message.answer("🛡 <b>Protected admin account.</b>", parse_mode="HTML")
                result = handlers["users_col"].update_one(
                    {"_id": target_uid, "banned": target.get("banned", False)},
                    {"$set": {"banned": requested_ban}})
                if not result.matched_count:
                    return await message.answer(
                        "⚠️ User status changed during the request. Please retry.")
                await state.clear()
                return await message.answer(
                    f"{'🚫' if requested_ban else '✅'} <b>User <code>{target_uid}</code> "
                    f"{'banned' if requested_ban else 'unbanned'} successfully.</b>",
                    parse_mode="HTML")
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
        if action == "ref":
            await message.answer(f"✅ <b>Ref revenue set to <code>{pct:g}%</code>.</b>", parse_mode="HTML")
            return
        if action == "support":
            await message.answer("✅ <b>Support URL updated.</b>", parse_mode="HTML")
            return
        await bot.edit_message_text(chat_id=data["config_chat"], message_id=data["config_message"],
                                    text=f"✅ {escape(action.title())} setting saved.", reply_markup=menu(message.from_user.id))
        try:
            await message.delete()
        except Exception:
            pass

    def payment_menu(uid=None):
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Add Payment Method", callback_data="adm_pay_add")
        kb.button(text="🗑 Remove Payment Method", callback_data="adm_pay_remove")
        kb.button(text="🔘 Enable / Disable Method", callback_data="adm_pay_methods")
        kb.button(text="🔄 Manual ON/OFF", callback_data="adm_pay_toggle")
        kb.button(text="⚡ Automatic UPI Gateway", callback_data="gw_settings")
        kb.button(text="⬅️ Back to Admin", callback_data="admin_panel")
        kb.adjust(1)
        return kb.as_markup()

    def manual_enabled():
        return (settings.find_one({"_id": "manual_payments"}) or {}).get("enabled", False)

    @dp.callback_query(F.data == "adm_pending")
    async def pending_deposits(cq):
        if not is_admin(cq.from_user.id, "payments"):
            return await cq.answer("Not authorized", show_alert=True)
        pending = list(database["manual_deposits"].find(
            {"status": {"$in": ["pending", "processing"]}}).sort("created_at", -1).limit(20))
        lines = ["🧾 <b>Pending Manual Deposits</b>", ""]
        kb = InlineKeyboardBuilder()
        for entry in pending:
            lines.append(f"🧾 <b>Deposit ID:</b> <code>{entry.get('deposit_id', str(entry['_id']))}</code>\n👤 <b>User:</b> <code>{entry['user_id']}</code>\n💰 <b>Amount:</b> ₹{entry['amount']}\n⏳ <b>Status:</b> {escape(entry.get('status', 'pending'))}\n")
            if entry.get("status") in ("pending", "processing"):
                kb.button(text=f"📸 Proof #{entry.get('deposit_id', str(entry['_id'])[-6:])}",
                          callback_data=f"adm_proof:{entry['_id']}")
        kb.button(text="⬅️ Back", callback_data="admin_panel")
        kb.adjust(1)
        await cq.message.edit_text("\n".join(lines) if pending else "🧾 No pending deposits.",
                                   reply_markup=kb.as_markup(), parse_mode="HTML")
        await cq.answer()

    @dp.callback_query(F.data.startswith("adm_proof:"))
    async def pending_proof(cq):
        if not is_admin(cq.from_user.id, "payments"):
            return await cq.answer("Not authorized", show_alert=True)
        from bson import ObjectId
        try:
            entry = database["manual_deposits"].find_one({"_id": ObjectId(cq.data.split(":")[1])})
        except Exception:
            entry = None
        if not entry:
            return await cq.answer("Request missing", show_alert=True)
        kb = InlineKeyboardBuilder()
        if entry.get("status") in ("pending", "processing"):
            kb.button(text=("🔄 Finish Approval" if entry.get("status") == "processing" else "✅ Approve"), callback_data=f"mr:approve:{entry['_id']}")
        if entry.get("status") == "pending":
            kb.button(text="❌ Reject", callback_data=f"mr:reject:{entry['_id']}")
            kb.button(text="📝 Custom Amount", callback_data=f"mr:custom:{entry['_id']}")
        kb.button(text="⬅️ Pending", callback_data="adm_pending")
        kb.adjust(1)
        # Proof is a separate attachment; the admin dashboard message remains intact.
        await bot.send_photo(cq.message.chat.id, entry["proof"],
            caption=f"🧾 <b>Deposit ID:</b> <code>{entry.get('deposit_id', str(entry['_id']))}</code>\n👤 <b>User:</b> <code>{entry['user_id']}</code>\n💰 <b>Amount:</b> ₹{entry['amount']}",
            reply_markup=kb.as_markup(), parse_mode="HTML")
        await cq.answer()

    @dp.callback_query(F.data == "adm_payments")
    async def payment_panel(cq):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        count = payment_methods.count_documents({})
        await cq.message.edit_text(
            f"💳 <b>Manage Payment Methods</b>\n\n"
            f"<b>Manual Payments:</b> {'🟢 ON' if manual_enabled() else '🔴 OFF'}\n"
            f"<b>Configured Methods:</b> <code>{count}</code>\n"
            "<b>Automatic UPI:</b> Existing gateway settings",
            reply_markup=payment_menu(cq.from_user.id), parse_mode="HTML")
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
        await cq.message.edit_text("➕ <b>Add Payment Method</b>\n\nSend payment method name (e.g. <code>PhonePe</code>).\n/cancel to stop.", parse_mode="HTML")
        await cq.answer()

    @dp.message(StateFilter(PaymentMethodState.name))
    async def payment_name(message, state):
        if not is_admin(message.from_user.id, "payments"):
            await state.clear()
            return
        name = (message.text or "").strip()
        if not 1 <= len(name) <= 60:
            return await message.answer("Enter a name up to 60 characters.")
        await state.update_data(pay_name=name)
        await state.set_state(PaymentMethodState.qr)
        data = await state.get_data()
        await bot.edit_message_text(chat_id=data["pay_chat"], message_id=data["pay_message"],
                                    text="📸 <b>Payment QR</b>\n\nSend QR image, or type <code>skip</code>.", parse_mode="HTML")

    @dp.message(StateFilter(PaymentMethodState.qr))
    async def payment_qr(message, state):
        if not is_admin(message.from_user.id, "payments"):
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
        data = await state.get_data()
        await bot.edit_message_text(chat_id=data["pay_chat"], message_id=data["pay_message"],
                                    text="📝 <b>Payment Instructions</b>\n\nSend payment instructions / UPI ID (max 500 characters).", parse_mode="HTML")

    @dp.message(StateFilter(PaymentMethodState.caption))
    async def payment_caption(message, state):
        if not is_admin(message.from_user.id, "payments"):
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
            parse_mode="HTML", reply_markup=payment_menu(message.from_user.id))
        try:
            await message.delete()
        except Exception:
            pass

    @dp.callback_query(F.data == "adm_pay_methods")
    async def payment_method_status(cq):
        if not is_admin(cq.from_user.id, "payments"):
            return await cq.answer("Not authorized", show_alert=True)
        kb = InlineKeyboardBuilder()
        for method in payment_methods.find({}).limit(50):
            kb.button(text=("🟢 " if method.get("enabled", True) else "🔴 ") + method["name"][:35],
                      callback_data=f"adm_pay_switch:{method['_id']}")
        kb.button(text="⬅️ Back", callback_data="adm_payments")
        kb.adjust(1)
        await cq.message.edit_text("🔘 <b>Payment Methods</b>\n\nTap a method to enable or disable it.", reply_markup=kb.as_markup(), parse_mode="HTML")
        await cq.answer()

    @dp.callback_query(F.data.startswith("adm_pay_switch:"))
    async def payment_method_switch(cq):
        if not is_admin(cq.from_user.id, "payments"):
            return await cq.answer("Not authorized", show_alert=True)
        from bson import ObjectId
        try:
            oid = ObjectId(cq.data.partition(":")[2])
        except Exception:
            return await cq.answer("Invalid method", show_alert=True)
        method = payment_methods.find_one({"_id": oid})
        if not method:
            return await cq.answer("Method missing", show_alert=True)
        payment_methods.update_one({"_id": oid}, {"$set": {"enabled": not method.get("enabled", True)}})
        await payment_method_status(cq)

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
        await cq.message.edit_text("🗑 <b>Remove Payment Method</b>\n\nSelect a method:" if methods else "ℹ️ <b>No manual payment methods configured.</b>",
                                   reply_markup=kb.as_markup(), parse_mode="HTML")
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
        await cq.message.edit_text(f"🗑 <b>Remove Payment Method?</b>\n\n<code>{escape(method['name'])}</code>", reply_markup=kb.as_markup(), parse_mode="HTML")
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
        await cq.message.edit_text("✅ Payment Method Removed", reply_markup=payment_menu(cq.from_user.id))
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
                text = "📊 <b>Manage Stock</b>\nNo available accounts."
            else:
                text = "📊 <b>Manage Stock</b>\nSelect a country:"
                for i, country in enumerate(countries):
                    count = numbers.count_documents({"country": country, "used": False})
                    kb.button(text=f"🌍 {country} ({count})", callback_data=f"stk:c:{i}")
        elif ci is None or ci >= len(countries):
            return await render_stock(cq)
        else:
            country = countries[ci]
            cats = stock_categories(country)
            if level == 1:
                text = f"🌍 <b>{escape(country)}</b>\nSelect a category:"
                for i, cat in enumerate(cats):
                    count = numbers.count_documents(stock_filter(country, cat))
                    kb.button(text=f"{'🟢 HEALTHY' if cat == 'Good' else cat} ({count})", callback_data=f"stk:k:{ci}:{i}")
            elif ki is None or ki >= len(cats):
                return await render_stock(cq, 1, ci)
            else:
                cat = cats[ki]
                years = stock_years(country, cat)
                if level == 2:
                    text = f"🌍 {escape(country)}\nCategory: <b>{escape(cat)}</b>\nSelect a year:"
                    for i, year in enumerate(years):
                        count = numbers.count_documents(stock_filter(country, cat, year))
                        kb.button(text=f"📅 {year} ({count})", callback_data=f"stk:y:{ci}:{ki}:{i}")
                elif yi is None or yi >= len(years):
                    return await render_stock(cq, 2, ci, ki)
                else:
                    year = years[yi]
                    docs = list(numbers.find(stock_filter(country, cat, year), {"price": 1}))
                    prices = sorted({str(d.get("price", "Not set")) for d in docs})
                    text = (f"📊 <b>Stock Price Editor</b>\n🌍 {escape(country)}\n"
                            f"Category: {escape(cat)}\n📅 Year: {escape(year)}\n"
                            f"📦 Accounts: {len(docs)}\n💰 Current prices: {escape(', '.join(prices[:10]))}\n\n"
                            "Change price for ALL available accounts in this category/year?")
                    kb.button(text="💰 Change Price", callback_data=f"stk:p:{ci}:{ki}:{yi}")
            kb.button(text="⬅️ Back", callback_data=("stk:home" if level == 1 else
                      f"stk:c:{ci}" if level == 2 else f"stk:k:{ci}:{ki}"))
        kb.button(text="🏠 Admin Panel", callback_data="admin_panel")
        kb.adjust(1)
        await cq.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

    @dp.callback_query(F.data == "adm_single_price")
    async def single_price_start(cq, state):
        if not is_admin(cq.from_user.id, "stock"):
            return await cq.answer("Not authorized", show_alert=True)
        await state.set_state(SingleStockPrice.waiting)
        await state.update_data(single_chat=cq.message.chat.id, single_message=cq.message.message_id)
        await cq.message.edit_text("📞 Send a phone number to search, or phone + INR price to edit.\n"
                                   "Examples: +919876543210  OR  +919876543210 120\n"
                                   "Price edits apply only to available accounts. /cancel to abort.")
        await cq.answer()

    @dp.message(StateFilter(SingleStockPrice.waiting), Command("cancel"))
    async def single_price_cancel(message, state):
        await state.clear()
        await message.answer("Cancelled.")

    @dp.message(StateFilter(SingleStockPrice.waiting))
    async def single_price_save(message, state):
        if not is_admin(message.from_user.id, "stock"):
            await state.clear()
            return
        import re
        from pymongo import ReturnDocument
        parts = (message.text or "").strip().split()
        if len(parts) not in (1, 2) or not re.fullmatch(r"\\+?[0-9]{8,15}", parts[0]):
            return await message.answer("❌ Format: phone_number [optional_price]")
        phone = parts[0].lstrip("+")
        lookup = {"number": {"$in": [phone, "+" + phone]}}
        data = await state.get_data()
        if len(parts) == 1:
            record = numbers.find_one(lookup, {"number": 1, "country": 1,
                "year": 1, "category": 1, "status": 1, "price": 1, "used": 1})
            if not record:
                return await message.answer("❌ No account found for that phone.")
            text = (
                f"📞 <b>Account Search Result</b>\n"
                f"Phone: <code>{escape(str(record.get('number', phone)))}</code>\n"
                f"Country: {escape(str(record.get('country', 'Unknown')))}\n"
                f"Year: {escape(str(record.get('year', 'Unknown')))}\n"
                f"Category: {escape(str(record.get('category', 'Good')))}\n"
                f"Status: {escape(str(record.get('status', 'Unknown')))}\n"
                f"Price: ₹{escape(str(record.get('price', 'Not set')))}\n"
                f"Stock: {'Sold' if record.get('used') else 'Available'}"
            )
        else:
            try:
                price = Decimal(parts[1])
                if (not price.is_finite() or
                        not Decimal("0.01") <= price <= Decimal("100000") or
                        price.as_tuple().exponent < -2):
                    raise InvalidOperation()
            except (InvalidOperation, ValueError):
                return await message.answer("❌ Invalid INR price.")
            record = numbers.find_one_and_update(
                dict(lookup, used=False), {"$set": {"price": float(price)}},
                return_document=ReturnDocument.AFTER
            )
            if not record:
                return await message.answer("❌ Available account not found.")
            text = f"✅ Updated <code>{escape(phone)}</code> to ₹{price:.2f}"

        await state.clear()
        await bot.edit_message_text(chat_id=data["single_chat"],
                                    message_id=data["single_message"], text=text,
                                    reply_markup=menu(message.from_user.id))
        try:
            await message.delete()
        except Exception:
            pass

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
                f"💰 Enter new INR price for {escape(countries[ci])} / {escape(cats[ki])} / {escape(years[yi])}.\n"
                "All matching AVAILABLE accounts will be updated.\nSend /cancel to abort.")
        await cq.answer()

    @dp.message(StateFilter(StockPrice.waiting_price), Command("cancel"))
    async def stock_cancel(message, state):
        await state.clear()
        await message.answer("❌ Price edit cancelled. Open Admin Panel to continue.")

    @dp.message(StateFilter(StockPrice.waiting_price))
    async def stock_save_price(message, state):
        if not is_admin(message.from_user.id, "stock"):
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
            text=(f"✅ <b>Stock Price Updated</b>\n🌍 {escape(data['stock_country'])}\n"
                  f"Category: {escape(data['stock_category'])}\n📅 Year: {escape(data['stock_year'])}\n"
                  f"💰 New price: ₹{price:.2f}\n📦 Updated accounts: {result.modified_count}"),
            reply_markup=menu(message.from_user.id), parse_mode="HTML")
        try:
            await message.delete()
        except Exception:
            pass

    @dp.callback_query(F.data == "admin_user_lookup")
    async def user_lookup_start(cq, state):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        await state.set_state(AdminUserLookup.waiting_id)
        await state.update_data(lookup_chat=cq.message.chat.id, lookup_message=None)
        sent = await cq.message.answer("👤 <b>Enter User ID:</b>\n\nSend <i>/cancel</i> only if you want to abort.", parse_mode="HTML")
        await state.update_data(lookup_message=sent.message_id)
        await cq.answer()

    @dp.message(StateFilter(AdminUserLookup.waiting_id), Command("cancel"))
    async def cancel_user_lookup(message, state):
        await state.clear()
        await message.answer("Cancelled.")

    @dp.message(StateFilter(AdminUserLookup.waiting_id))
    async def user_lookup(message, state):
        if not is_admin(message.from_user.id, "users"):
            await state.clear()
            return
        value = (message.text or "").strip()
        if not value.isascii() or not value.isdecimal() or not 0 < int(value) < 10**16:
            return await message.answer("❌ Send a valid numeric User ID.")
        user = handlers["users_col"].find_one({"_id": int(value)})
        if not user:
            return await message.answer("❌ User not found.")
        from decimal import Decimal
        from html import escape
        uid = int(value)
        orders = list(database["orders"].find(
            {"user_id": uid, "status": "purchased"}, {"price": 1}))
        spent = sum((Decimal(str(o.get("price") or 0)) for o in orders), Decimal("0"))
        gateway = list(database["gateway_payments"].find(
            {"user_id": uid, "status": "paid"}, {"amount": 1}))
        upi = sum((Decimal(str(p.get("amount") or 0)) for p in gateway), Decimal("0"))
        manual = list(database["manual_deposits"].find(
            {"user_id": uid, "status": "approved"}, {"amount": 1, "approved_amount": 1}))
        manual_total = sum(
            (Decimal(str(p.get("approved_amount", p.get("amount")) or 0)) for p in manual),
            Decimal("0"))
        deposited = upi + manual_total
        joined = user.get("joined_at", user.get("created_at"))
        joined_text = joined.strftime("%Y-%m-%d %H:%M:%S") if hasattr(joined, "strftime") else str(joined or "Unknown")
        data = await state.get_data()
        await state.clear()
        await bot.edit_message_text(
            chat_id=data["lookup_chat"], message_id=data["lookup_message"],
            text=(
                f"👤 <b>USER INFO:</b> <code>{uid}</code>\n\n"
                f"💰 <b>Balance:</b> ₹{Decimal(str(user.get('balance') or 0)):g}\n"
                f"💳 <b>Total Deposited:</b> ₹{deposited:g}\n"
                f"🏦 <b>UPI Deposited:</b> ₹{upi:g}\n"
                f"🛒 <b>Total Orders:</b> <code>{len(orders)}</code>\n"
                f"💵 <b>Total Spent:</b> ₹{spent:g}\n"
                f"🎁 <b>Discount:</b> {Decimal(str(user.get('discount_percent') or 0)):g}%\n"
                f"📅 <b>Joined:</b> <code>{escape(joined_text)}</code>\n"
                f"{'🔴' if user.get('banned') else '🟢'} <b>Banned:</b> {'Yes' if user.get('banned') else 'No'}"
            ),
            parse_mode="HTML"
        )

    @dp.message(Command("admin"))
    async def admin_command(message):
        if not is_admin(message.from_user.id):
            return await message.answer("❌ Not authorized.")
        await message.answer("🛡 <b>Admin Panel</b>", reply_markup=menu(message.from_user.id), parse_mode="HTML")

    @dp.callback_query(F.data == "admin_panel")
    async def admin_callback(cq):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        await cq.message.edit_text("🛡 <b>Advanced Admin Dashboard</b>", reply_markup=menu(cq.from_user.id), parse_mode="HTML")
        await cq.answer()

    @dp.callback_query(F.data.startswith("admin_do:"))
    async def admin_action(cq, state):
        if not is_admin(cq.from_user.id):
            return await cq.answer("Not authorized", show_alert=True)
        command = cq.data.partition(":")[2]
        if command == "changebalance":
            await state.clear()
            await state.set_state(AdminBalance.waiting_change)
            await state.update_data(balance_chat=cq.message.chat.id, balance_message=None)
            sent = await cq.message.answer("💰 <b>Change Balance</b>\n\nSend <b>User ID</b> and <b>amount</b> in one message:\n\n<code>1234567890 10</code> = Add ₹10\n<code>1234567890 -10</code> = Deduct ₹10\n\n/cancel to stop.", parse_mode="HTML")
            await state.update_data(balance_message=sent.message_id)
        elif command == "broadcast":
            await state.set_state(AdminBroadcast.waiting_message)
            await state.update_data(broadcast_chat=cq.message.chat.id,
                                    broadcast_message=None)
            sent = await cq.message.answer(
                "📢 Send text, a photo or a video to broadcast.\n"
                "Optional button on its own line: BUTTON: Support | https://t.me/username\n"
                "/cancel to stop.")
            await state.update_data(broadcast_message=sent.message_id)
        elif command in handlers:
            # Reuse existing command handlers while keeping the original
            # admin panel message (rather than sending a second navigation message).
            class PanelMessageProxy:
                def __init__(self, source, sender):
                    self._source = source
                    self.from_user = sender

                def __getattr__(self, key):
                    return getattr(self._source, key)

                async def answer(self, text, **kwargs):
                    return await (self._source.answer(text, **kwargs) if command == "add" else self._source.edit_text(text, **kwargs))

            msg = PanelMessageProxy(cq.message, cq.from_user)
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
        if not is_admin(message.from_user.id, "broadcast"):
            await state.clear()
            return
        panel = await state.get_data()
        await state.clear()
        await bot.edit_message_text(chat_id=panel["broadcast_chat"],
                                    message_id=panel["broadcast_message"],
                                    text="📢 Broadcast in progress...")
        result = await handlers["broadcast_panel"](message)
        if result is None:
            text = "❌ Broadcast cancelled: access revoked."
        else:
            sent, failed = result
            text = f"✅ Broadcast complete: {sent} sent, {failed} failed."
        await bot.edit_message_text(chat_id=panel["broadcast_chat"],
                                    message_id=panel["broadcast_message"],
                                    text=text, reply_markup=menu(message.from_user.id))

    @dp.message(StateFilter(AdminBalance.waiting_change), Command("cancel"))
    async def cancel_balance(message: Message, state):
        await state.clear()
        await message.answer("❌ Change Balance cancelled.")

    @dp.message(StateFilter(AdminBalance.waiting_change))
    async def change_balance(message: Message, state):
        if not is_admin(message.from_user.id, "users"):
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
        data = await state.get_data()
        await state.clear()
        action = "Deducted" if deduct else "Added"
        result_text = (
            f"✅ Balance {action}!\n🆔 User ID: <code>{target}</code>\n"
            f"{'➖' if deduct else '➕'} {action}: ₹{abs(amount):.2f}\n"
            f"💰 New Balance: ₹{updated.get('balance', 0):.2f}"
        )
        await bot.edit_message_text(
            chat_id=data["balance_chat"], message_id=data["balance_message"],
            text=result_text, parse_mode="HTML",
            reply_markup=menu(message.from_user.id)
        )
        try:
            await bot.send_message(target, f"💰 Admin {action.lower()} ₹{abs(amount):.2f} {'from' if deduct else 'to'} your wallet.")
        except Exception:
            pass
