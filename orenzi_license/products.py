"""Add product, from the customer's own site: the page /orenzi-products asks the control plane what this customer
has and could add, and sends a request for one. The control plane makes a 'Trial Requested' subscription that an
Orenzi officer approves; nothing is built or billed before that.

Both calls are signed with this site's plan secret (`orenzi_plan_secret`), like the daily usage report, so the
control plane knows which customer is asking. Only the people who act for the customer may use the page: System
Managers, and the roles products add in the hook `orenzi_account_roles` (the club site adds Platform Admin).
"""

import json
import time

import frappe
from frappe import _

from orenzi_license.plan import sign

TIMEOUT = 15


class NotWired(frappe.ValidationError):
	pass


def account_roles() -> set:
	return {"System Manager", *(frappe.get_hooks("orenzi_account_roles") or [])}


def can_manage(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user in ("Guest", None):
		return False
	return bool(account_roles() & set(frappe.get_roles(user)))


def _check_manager() -> None:
	if not can_manage():
		frappe.throw(
			_("Only the people who manage this Orenzi account can add a product."), frappe.PermissionError
		)


def wired() -> bool:
	conf = frappe.conf
	return bool(
		conf.get("orenzi_control_plane_url") and conf.get("orenzi_plan_secret") and conf.get("orenzi_tenant")
	)


def _call(method: str, body: dict) -> dict:
	"""POST a signed request to the control plane and return its `message`. Raises NotWired on a site that has no
	control plane (a developer's or a demo site), and a ValidationError carrying the control plane's own message
	when it refuses."""
	import requests

	if not wired():
		raise NotWired(_("This site is not connected to Orenzi's control plane."))
	conf = frappe.conf
	payload = json.dumps({**body, "tenant": conf.orenzi_tenant, "ts": int(time.time())}, sort_keys=True)
	try:
		response = requests.post(
			f"{conf.orenzi_control_plane_url.rstrip('/')}/api/method/orenzi_saas.api.{method}",
			data={"payload": payload, "signature": sign(conf.orenzi_plan_secret, payload)},
			timeout=TIMEOUT,
		)
	except requests.RequestException:
		frappe.throw(_("Could not reach Orenzi just now. Please try again in a few minutes."))
	try:
		answer = response.json()
	except ValueError:
		answer = {}
	if not response.ok:
		frappe.throw(
			_server_message(answer) or _("Orenzi could not take this request. Please try again later.")
		)
	return answer.get("message") or {}


def _server_message(answer: dict) -> str:
	"""The text of the control plane's refusal (Frappe sends it in `_server_messages`), without markup."""
	try:
		messages = json.loads(answer.get("_server_messages") or "[]")
		text = json.loads(messages[0]).get("message") if messages else ""
	except (ValueError, TypeError, AttributeError, IndexError):
		text = ""
	return frappe.utils.strip_html(text or "")[:300]


@frappe.whitelist()
def get_offers(lang: str = "en") -> dict:
	"""What this customer has and could add, with prices, in the page's language."""
	_check_manager()
	return _call("site_offers", {"lang": lang if lang in ("en", "hi", "mr") else "en"})


@frappe.whitelist(methods=["POST"])
def request_product(product: str, plan: str, billing_interval: str = "Monthly") -> dict:
	"""Ask Orenzi for a trial of another product on this customer's account."""
	_check_manager()
	if billing_interval not in ("Monthly", "Annual"):
		frappe.throw(_("Invalid choice."))
	user = frappe.get_cached_doc("User", frappe.session.user)
	return _call(
		"site_request_product",
		{
			"product": product,
			"plan": plan,
			"billing_interval": billing_interval,
			"requested_by": {"email": user.email or user.name, "full_name": user.full_name or ""},
		},
	)
