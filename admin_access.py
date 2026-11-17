"""Shared owner/subadmin authorization used by dashboard, callbacks and commands.

All authorization is checked against MongoDB at action time; hiding a button is never
considered an authorization check.
"""

ADMIN_PERMISSIONS = frozenset({
    "stock", "payments", "users", "stats", "broadcast", "settings",
    "backup", "accounts"
})

def authorized(uid, owner_ids, registry, permission=None):
    if uid in owner_ids:
        return True
    if permission is not None and permission not in ADMIN_PERMISSIONS:
        return False
    record = registry.find_one({"_id": uid, "active": True})
    return bool(record and (permission is None or
                           permission in record.get("permissions", [])))

def callback_permission(action):
    """Return the permission category; None permits any active admin."""
    if action == "admin_panel":
        return None
    if action.startswith(("stk:", "admin_stock_info", "adm_single_price",
                          "admin_do:setprices", "admin_do:db")):
        return "stock"
    if action.startswith(("adm_pay", "adm_pending", "adm_proof:", "gw_",
                          "mr:approve:", "mr:reject:", "mr:custom:", "pay_wd:")):
        return "payments"
    if action.startswith(("adm_stats", "livecredits:")):
        return "stats"
    if action.startswith(("adm_backup", "adm_restore")):
        return "backup"
    if action.startswith(("admin_user_lookup", "adm_config:ban",
                          "adm_config:discount", "admin_do:changebalance")):
        return "users"
    if action.startswith("admin_do:broadcast"):
        return "broadcast"
    if action.startswith(("admin_do:add", "admin_do:remove",
                          "add_country:", "remove_country:", "removecountry:",
                          "approve_sell:", "reject_sell:")):
        return "accounts"
    return "settings"

def owner_only_action(action):
    return action.startswith(("adm_admins", "adm_admin_add",
                              "adm_admin_remove", "adm_setbio"))
