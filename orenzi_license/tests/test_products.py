"""Add product from the site (products.py and the /orenzi-products page)."""

import importlib
import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from orenzi_license import plan, products
from orenzi_license.tests.test_license import hooks

SECRET = "test-secret-not-real"
CONF = {
	"orenzi_control_plane_url": "https://cp.orenzi.test/",
	"orenzi_plan_secret": SECRET,
	"orenzi_tenant": "lic-club",
}
page = importlib.import_module("orenzi_license.www.orenzi_products")


def reply(status=200, body=None):
	response = MagicMock(ok=status < 400, status_code=status)
	response.json.return_value = body or {}
	return response


def user(email, *roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	doc = frappe.get_doc("User", email)
	if roles:
		doc.add_roles(*roles)
	return doc


class TestAddProductFromSite(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._conf = {k: frappe.conf.get(k) for k in CONF}
		frappe.conf.update(CONF)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.conf.update(self._conf)
		frappe.form_dict.clear()
		frappe.db.rollback()

	def test_who_may_add_a_product(self):
		if not frappe.db.exists("Role", "Lic Account Owner"):
			frappe.get_doc({"doctype": "Role", "role_name": "Lic Account Owner"}).insert(
				ignore_permissions=True
			)
		user("lic.owner@shop.test", "System Manager")
		user("lic.cashier@shop.test")
		user("lic.president@club.test", "Lic Account Owner")
		self.assertTrue(products.can_manage("lic.owner@shop.test"))
		self.assertFalse(products.can_manage("lic.cashier@shop.test"))
		self.assertFalse(products.can_manage("Guest"))
		self.assertFalse(products.can_manage("lic.president@club.test"))
		with hooks(
			orenzi_account_roles=["Lic Account Owner"]
		):  # what a product adds (the club: Platform Admin)
			self.assertTrue(products.can_manage("lic.president@club.test"))
		frappe.set_user("lic.cashier@shop.test")
		with patch("requests.post") as post, self.assertRaises(frappe.PermissionError):
			products.request_product("pos", "POS")
		post.assert_not_called()

	def test_a_request_is_signed_with_the_site_secret_and_names_the_person(self):
		user("lic.owner@shop.test", "System Manager")
		frappe.set_user("lic.owner@shop.test")
		answer = {"message": {"subscription": "lic-club.pos", "status": "Trial Requested"}}
		with patch("requests.post", return_value=reply(body=answer)) as post:
			self.assertEqual(products.request_product("pos", "POS", "Annual"), answer["message"])
		url, data = post.call_args.args[0], post.call_args.kwargs["data"]
		self.assertEqual(url, "https://cp.orenzi.test/api/method/orenzi_saas.api.site_request_product")
		self.assertEqual(data["signature"], plan.sign(SECRET, data["payload"]))
		body = json.loads(data["payload"])
		self.assertEqual((body["tenant"], body["product"], body["plan"]), ("lic-club", "pos", "POS"))
		self.assertEqual(body["billing_interval"], "Annual")
		self.assertEqual(body["requested_by"]["email"], "lic.owner@shop.test")
		self.assertIsInstance(body["ts"], int)

	def test_the_control_planes_refusal_reaches_the_person(self):
		refusal = {
			"_server_messages": json.dumps(
				[
					json.dumps(
						{"message": "<b>Please settle your current Orenzi bill before adding a product.</b>"}
					)
				]
			)
		}
		with patch("requests.post", return_value=reply(417, refusal)):
			with self.assertRaises(frappe.ValidationError) as caught:
				products.request_product("pos", "POS")
		self.assertIn("Please settle your current Orenzi bill", str(caught.exception))
		self.assertNotIn("<b>", str(caught.exception))

	def test_a_site_without_a_control_plane_says_so(self):
		frappe.conf.orenzi_control_plane_url = ""
		self.assertFalse(products.wired())
		with patch("requests.post") as post, self.assertRaises(products.NotWired):
			products.get_offers()
		post.assert_not_called()
		frappe.form_dict.update({"lang": "en"})
		ctx = page.get_context(frappe._dict())
		self.assertIn("not connected", ctx.problem)

	def test_the_page_lists_the_customers_products_and_the_others(self):
		offers = {
			"message": {
				"account": "Lic Club",
				"trial_days": 14,
				"blocked": False,
				"products": [
					{"product": "club", "name": "Club site", "intro": "", "unit_note": "", "status": "Active",
					 "plans": []},
					{"product": "pos", "name": "Shop POS", "intro": "Billing for your shop.", "unit_note": "",
					 "status": None, "plans": [{"name": "POS", "title": "POS", "price_text": "₹999 per till / month",
												  "members": "", "annual_months_free": 2}]},
				],
			}
		}  # fmt: skip
		frappe.form_dict.update({"lang": "en"})
		with patch("requests.post", return_value=reply(body=offers)):
			ctx = page.get_context(frappe._dict())
		self.assertEqual(ctx.problem, "")
		self.assertEqual([(p["name"], p["status_text"]) for p in ctx.mine], [("Club site", "active")])
		self.assertEqual(ctx.addable[0]["submit_text"], "Request a trial of Shop POS")
		html = frappe.render_template("orenzi_license/www/orenzi-products.html", ctx)
		self.assertIn("₹999 per till / month", html)
		self.assertIn('value="pos"', html)
		self.assertIn("orenzi_license.products.request_product", html)

	def test_a_guest_is_sent_to_log_in(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.Redirect):
			page.get_context(frappe._dict())
		self.assertIn("redirect-to=/orenzi-products", frappe.local.flags.redirect_location)
