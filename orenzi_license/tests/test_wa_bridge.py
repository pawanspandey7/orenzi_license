"""The WhatsApp bridge. The dev club site has no wa_inbox, so its parts are stood in for where needed."""

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from orenzi_license import plan
from orenzi_license.bridges import wa


class TestWaBridge(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_on_a_site_without_the_inbox_it_does_nothing(self):
		self.assertFalse(wa.installed())
		self.assertEqual(wa.daily_counts(), {})
		self.assertEqual(wa.read_only_modules(), ())

	def test_meta_categories_become_metrics(self):
		self.assertEqual(wa.metric_for("MARKETING"), "wa_marketing")
		self.assertEqual(wa.metric_for("authentication-international"), "wa_authentication_international")
		self.assertIsNone(wa.metric_for(""))

	def test_only_what_meta_called_billable_is_counted_by_day_and_category(self):
		rows = [
			frappe._dict(
				day="2027-03-01", pricing_json=json.dumps({"billable": True, "category": "marketing"})
			),
			frappe._dict(
				day="2027-03-01", pricing_json=json.dumps({"billable": True, "category": "marketing"})
			),
			frappe._dict(
				day="2027-03-01", pricing_json=json.dumps({"billable": False, "category": "service"})
			),
			frappe._dict(
				day="2027-03-02", pricing_json=json.dumps({"billable": True, "category": "utility"})
			),
			frappe._dict(day="2027-03-02", pricing_json="not json"),
		]
		with patch.object(wa, "installed", return_value=True), patch("frappe.db.sql", return_value=rows):
			counts = wa.daily_counts(days=3, on="2027-03-03")
		self.assertEqual(
			counts,
			{"2027-03-01": {"wa_marketing": 2}, "2027-03-02": {"wa_utility": 1}, "2027-03-03": {}},
		)

	def test_a_suspended_site_cannot_send(self):
		with patch.object(wa, "installed", return_value=True):
			self.assertTrue(plan.is_protected("WhatsApp Message", "Frappe Whatsapp"))
			self.assertTrue(plan.is_protected("WA Conversation", "WA Inbox"))
			self.assertFalse(plan.is_protected("User", "Core"))

	def test_daily_counts_are_merged_into_the_usage_push(self):
		sent = {}

		class Response:
			ok = True

		def post(url, data=None, timeout=None):
			sent.update(json.loads(data["payload"]))
			return Response()

		conf = {
			"orenzi_control_plane_url": "https://cp.test",
			"orenzi_plan_secret": "s",
			"orenzi_tenant": "t.whatsapp",
		}
		with (
			patch.dict(frappe.conf, conf),
			patch.object(wa, "daily_counts", return_value={"2027-03-01": {"wa_marketing": 2}}),
			patch("requests.post", side_effect=post),
		):
			self.assertTrue(plan.push_usage())
		self.assertEqual(sent["daily"], {"2027-03-01": {"wa_marketing": 2}})
		self.assertEqual(sent["tenant"], "t.whatsapp")
