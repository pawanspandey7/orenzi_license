import json
from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from orenzi_license import plan

SECRET = "test-secret-not-real"


def install(status="Active", features=None, seq=1):
	text = json.dumps(
		{
			"tenant": "lic-test",
			"product": "pos",
			"plan": "Test",
			"seq": seq,
			"status": status,
			"features": features or {},
			"limits": {},
			"valid_until": str(now_datetime() + timedelta(days=14)),
		},
		sort_keys=True,
		separators=(",", ":"),
	)
	return plan.store_plan(text, plan.sign(SECRET, text))


def hooks(**values):
	"""Pretend the installed products declare these hooks (and nothing else)."""
	real = frappe.get_hooks

	def fake(*args, **kwargs):
		name = args[0] if args else kwargs.get("hook")
		if name in values:
			return values[name]
		if name and name.startswith("orenzi_"):
			return []
		return real(*args, **kwargs)

	return patch.object(frappe, "get_hooks", side_effect=fake)


class TestLicence(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._conf = (frappe.conf.get("orenzi_plan_secret"), frappe.conf.get("developer_mode"))
		frappe.conf.orenzi_plan_secret = SECRET
		frappe.conf.developer_mode = 0
		frappe.db.sql("delete from `tabSingles` where doctype = 'Plan Snapshot'")
		frappe.local._orenzi_snapshot = plan._UNSET

	def tearDown(self):
		frappe.conf.orenzi_plan_secret, frappe.conf.developer_mode = self._conf
		frappe.local._orenzi_snapshot = plan._UNSET
		frappe.db.rollback()

	def test_the_snapshot_doctype_belongs_to_this_app(self):
		self.assertEqual(frappe.db.get_value("DocType", "Plan Snapshot", "module"), "Orenzi License")

	def test_orenzi_core_plan_is_this_module(self):
		from orenzi_core import plan as old_name

		self.assertIs(old_name, plan)
		self.assertIs(frappe.get_attr("orenzi_core.plan.receive_plan"), plan.receive_plan)
		self.assertIn(plan.receive_plan, frappe.whitelisted)

	def test_core_features_come_from_the_products_hooks(self):
		with hooks(orenzi_core_features=["pos.billing"]):
			self.assertTrue(plan.feature_enabled("pos.billing"))
			self.assertFalse(plan.feature_enabled("members.registry"))

	def test_the_club_still_declares_its_core(self):
		self.assertTrue(
			{"members.registry", "directory.basic", "dues.collect", "receipts.80g"} <= plan.core_features()
		)

	def test_read_only_protects_what_the_products_name(self):
		with hooks(orenzi_read_only_modules=["Orenzi *", "Accounts"], orenzi_read_only_doctypes=["ToDo"]):
			self.assertTrue(plan.is_protected("Person", "Orenzi Core"))
			self.assertTrue(plan.is_protected("Sales Invoice", "Accounts"))
			self.assertTrue(plan.is_protected("ToDo", "Desk"))
			self.assertFalse(plan.is_protected("Note", "Desk"))
			self.assertFalse(plan.is_protected("Orenzi Plan", "Orenzi SaaS"))
			self.assertFalse(plan.is_protected("Plan Snapshot", "Orenzi License"))

	def test_a_suspended_site_refuses_edits_to_a_named_doctype(self):
		install(status="Suspended")
		frappe.set_user("Guest")
		note = frappe.get_doc({"doctype": "ToDo", "description": "x"})
		with hooks(orenzi_read_only_doctypes=["ToDo"]):
			with self.assertRaises(frappe.PermissionError):
				plan.block_writes_when_read_only(note)
		with hooks(orenzi_read_only_doctypes=[]):
			plan.block_writes_when_read_only(note)  # not protected: allowed

	def test_usage_merges_every_collector_and_survives_a_broken_one(self):
		with hooks(
			orenzi_usage_collectors=[
				"orenzi_license.plan.storage_usage",
				"orenzi_license.tests.test_license.broken_collector",
				"orenzi_license.tests.test_license.pos_collector",
			]
		):
			usage = plan.collect_usage()
		self.assertIn("storage_mb", usage)
		self.assertEqual(usage["outlets"], 3)

	def test_on_a_club_site_usage_is_what_it_was(self):
		self.assertEqual({"members", "clubs", "org_units", "storage_mb"} - set(plan.collect_usage()), set())

	def test_a_signed_snapshot_with_a_product_key_is_stored(self):
		self.assertTrue(install(features={"pos.kds": {"enabled": True}})["ok"])
		self.assertEqual(plan.get_snapshot()["product"], "pos")
		self.assertTrue(plan.feature_enabled("pos.kds"))


def pos_collector():
	return {"outlets": 3}


def broken_collector():
	raise RuntimeError("counter broke")
