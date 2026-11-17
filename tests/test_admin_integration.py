"""Lightweight safety regressions for the admin/recharge integration."""
from pathlib import Path
import ast
import unittest
from admin_access import authorized, callback_permission, owner_only_action

ROOT = Path(__file__).resolve().parents[1]

class IntegrationSafetyTests(unittest.TestCase):
    def source(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_python_syntax(self):
        for name in ("bot.py", "admin_menu.py", "gateway_recharge.py", "manual_recharge.py", "admin_access.py"):
            with self.subTest(name=name):
                ast.parse(self.source(name), filename=name)

    def test_manual_recharge_registration(self):
        bot = self.source("bot.py")
        self.assertIn("register_manual_recharge(dp, bot, db, ADMIN_IDS)", bot)
        self.assertIn('action == "gw_recharge" or action.startswith("gw_check:")', bot)

    def test_manual_credit_idempotency(self):
        source = self.source("manual_recharge.py")
        self.assertIn('"credited_manual_deposits": {"$ne": str(oid)}', source)
        self.assertIn('"status": "processing"', source)
        self.assertIn('"status": "approved"', source)
        self.assertIn('"status": "rejected"', source)

    def test_admin_security(self):
        bot = self.source("bot.py")
        admin = self.source("admin_menu.py")
        self.assertIn("class AdminActionMiddleware", bot)
        self.assertIn("class AdminPermissionMiddleware", admin)
        self.assertIn("permission_for(action)", admin)

    def test_owner_and_subadmin_permissions(self):
        class Registry:
            records = {
                20: {"_id": 20, "active": True, "permissions": ["stock"]},
                30: {"_id": 30, "active": False, "permissions": ["payments"]},
            }
            def find_one(self, query):
                data = self.records.get(query.get("_id"))
                if data and data.get("active") == query.get("active"):
                    return data
                return None
        registry = Registry()
        self.assertTrue(authorized(10, [10], registry, "payments"))
        self.assertTrue(authorized(20, [10], registry, "stock"))
        self.assertFalse(authorized(20, [10], registry, "payments"))
        self.assertFalse(authorized(20, [10], registry, "invalid_permission"))
        self.assertFalse(authorized(30, [10], registry, "payments"))
        self.assertFalse(authorized(99, [10], registry, None))

    def test_callback_access_categories(self):
        cases = {
            "admin_panel": None,
            "adm_single_price": "stock",
            "stk:home": "stock",
            "admin_do:setprices": "stock",
            "admin_do:broadcast": "broadcast",
            "adm_pending": "payments",
            "mr:approve:123": "payments",
            "gw_token_add": "payments",
            "admin_do:changebalance": "users",
            "adm_backup": "backup",
            "admin_do:add": "accounts",
            "admin_toggle_maintenance": "settings",
        }
        for action, expected in cases.items():
            with self.subTest(action=action):
                self.assertEqual(callback_permission(action), expected)
        self.assertTrue(owner_only_action("adm_setbio"))
        self.assertTrue(owner_only_action("adm_admin_add"))
        self.assertFalse(owner_only_action("adm_stats"))

    def test_gateway_verified_details_and_recovery(self):
        source = self.source("gateway_recharge.py")
        self.assertIn('verified_id = detail.get("order_id"', source)
        self.assertIn('verified_amount = Decimal(str(detail["amount"]))', source)
        self.assertIn('"credited_gateway_orders": {"$ne": order_id}', source)
        self.assertIn('"credited_referral_gateway_orders": {"$ne": order_id}', source)
        self.assertIn('"status": "paid"', source)

    def test_feature_hooks(self):
        bot = self.source("bot.py")
        admin = self.source("admin_menu.py")
        self.assertIn("discount_percent", bot)
        self.assertIn("get_support_url()", bot)
        for action in ("adm_restore", "adm_setbio", "adm_admins",
                       "adm_single_price", "adm_pay_methods", "adm_pay_toggle"):
            with self.subTest(action=action):
                self.assertIn(action, admin)

if __name__ == "__main__":
    unittest.main()
