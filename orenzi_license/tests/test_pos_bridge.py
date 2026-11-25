"""The POS bridge. The dev club site has no orenzi_pos, so the POS app is stood in for where it is needed."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from orenzi_license import plan, setup
from orenzi_license.bridges import pos


def features(*keys):
	return {f"pos.{k}": {"enabled": True} for k in keys}


class TestPosBridge(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_on_a_site_without_the_pos_it_does_nothing(self):
		self.assertFalse(pos.installed())
		self.assertEqual(pos.usage(), {})
		self.assertEqual(pos.read_only_modules(), ())
		with patch("frappe.installer.update_site_config") as write:
			pos.on_plan({"features": features(*pos.GOLD), "limits": {"terminals": 3}})
		write.assert_not_called()

	def test_the_tier_follows_the_features_the_plan_switches_on(self):
		self.assertEqual(pos.tier(features(*pos.GOLD)), "gold")
		self.assertEqual(pos.tier(features(*pos.SILVER)), "silver")
		self.assertEqual(pos.tier(features(*pos.SILVER[:-1])), "basic")
		self.assertEqual(pos.tier({"pos.loyalty": {"enabled": False}}), "basic")

	def test_a_snapshot_sets_the_pos_apps_plan_and_terminal_cap(self):
		with (
			patch.object(pos, "installed", return_value=True),
			patch("frappe.installer.update_site_config") as write,
		):
			pos.on_plan({"features": features(*pos.GOLD), "limits": {"terminals": 0}})
			pos.on_plan({"features": features(*pos.SILVER), "limits": {"terminals": 3}})
		self.assertEqual(
			[c.args for c in write.call_args_list],
			[
				("orenzi_pos_plan", "gold"),
				("orenzi_pos_max_terminals", pos.NO_CAP),
				("orenzi_pos_plan", "silver"),
				("orenzi_pos_max_terminals", 3),
			],
		)

	def test_a_suspended_shop_cannot_sell_or_change_its_books(self):
		with patch.object(pos, "installed", return_value=True):
			self.assertTrue(plan.is_protected("Sales Invoice", "Accounts"))
			self.assertTrue(plan.is_protected("POS Terminal", "Orenzi POS"))
			self.assertTrue(plan.is_protected("Item", "Stock"))
			self.assertFalse(plan.is_protected("User", "Core"))  # people can still sign in
			self.assertFalse(plan.is_protected("Plan Snapshot", "Orenzi License"))

	def test_company_abbreviations_are_what_erpnext_accepts(self):
		self.assertEqual(pos._abbr("Sharma General Store"), "SGS")
		self.assertEqual(pos._abbr("A"), "SHOP")
		self.assertEqual(pos._abbr("Kirana"), "KIR")  # one word: its first letters, not one letter

	def test_configure_puts_a_site_key_in_the_config_from_the_environment_only(self):
		env = {"ORENZI_PLAN_SECRET": "s-not-real", "ORENZI_SITE_KEY": "k-not-real"}
		with patch.dict("os.environ", env), patch("frappe.installer.update_site_config") as write:
			setup.configure("shop.pos", "https://app.example.test", "orenzi_pos_grant_private_key")
		self.assertIn(("orenzi_pos_grant_private_key", "k-not-real"), [c.args for c in write.call_args_list])
		for bad in ("db_password", "orenzi_plan_secret", "Bad Name"):
			with patch.dict("os.environ", env), patch("frappe.installer.update_site_config"):
				with self.assertRaises(frappe.ValidationError):
					setup.configure("shop.pos", "", bad)
