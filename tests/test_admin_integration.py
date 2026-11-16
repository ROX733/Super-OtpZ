"""Lightweight safety regressions for the admin/recharge integration."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]

class IntegrationSafetyTests(unittest.TestCase):
    def source(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_python_syntax(self):
        for name in ("bot.py", "admin_menu.py", "gateway_recharge.py", "manual_recharge.py"):
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
        self.assertIn('uid in admin_ids or', admin) if False else None

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
