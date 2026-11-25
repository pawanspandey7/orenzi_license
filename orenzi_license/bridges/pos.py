"""The bridge between Orenzi's control plane and the Orenzi POS app (greenadvise/Orenzi-POS) on a POS site.

Every function here does nothing unless `orenzi_pos` is installed on the site, so the same orenzi_license serves
club sites unchanged. It keeps the POS repository free of control-plane code:

- usage: the number of active terminals (what a POS bill charges for, Rs 999 a month each, owner 2026-11-26);
- read-only: a Suspended or Cancelled POS site refuses every change to its business records, sales included
  (owner, 2026-11-26: "billing band, baaki sab read-only"); terminals keep their own copy until it is paid;
- the plan: the POS app reads its tier and terminal cap from site_config (`orenzi_pos_plan`,
  `orenzi_pos_max_terminals`), so each signed snapshot is turned into those two values;
- a new shop: its company, books, tax classes and POS settings made by the POS app's own provisioning, from the
  customer's details on the control plane.
"""

import re

import frappe

# the POS app's tiers (orenzi_pos.entitlement.grant.PLAN_FEATURES), as control-plane feature keys "pos.<feature>"
SILVER = ("batch_expiry", "loyalty", "messaging", "dynamic_upi_qr", "tally_import", "erp_accounting")
GOLD = (*SILVER, "erp_hr", "online_ordering", "e_invoicing", "multi_store")
NO_CAP = 999  # what "no terminal cap" becomes for the POS app, which wants a whole number
# ERPNext and POS records a suspended shop may not change; Core, Desk and e-mail stay usable so people can sign in
READ_ONLY_MODULES = (
	"Orenzi POS", "Accounts", "Selling", "Buying", "Stock", "Setup", "CRM", "Assets", "Manufacturing",
	"Projects", "Support", "Quality Management", "Maintenance", "Subcontracting", "Regional", "Utilities",
)  # fmt: skip
# Default tax classes for a new shop (owner's decision, 2026-11-26); the shop's accountant can change them.
DEFAULT_TAX_CLASSES = [
	{"name": "GST 0%", "gst_rate": 0},
	{"name": "GST 5%", "gst_rate": 5},
	{"name": "GST 12%", "gst_rate": 12},
	{"name": "GST 18%", "gst_rate": 18},
	{"name": "GST 28%", "gst_rate": 28},
]


def installed() -> bool:
	return "orenzi_pos" in frappe.get_installed_apps()


def usage() -> dict:
	if not installed():
		return {}
	return {"terminals": frappe.db.count("POS Terminal", {"status": "Active"})}


def read_only_modules() -> tuple:
	return READ_ONLY_MODULES if installed() else ()


def tier(features: dict) -> str:
	on = {
		key[4:] for key, value in (features or {}).items() if key.startswith("pos.") and value.get("enabled")
	}
	if set(GOLD) <= on:
		return "gold"
	if set(SILVER) <= on:
		return "silver"
	return "basic"


def on_plan(data: dict) -> None:
	"""Called by orenzi_license.plan.store_plan after a new snapshot is stored."""
	if not installed():
		return
	from frappe.installer import update_site_config

	cap = int((data.get("limits") or {}).get("terminals") or 0) or NO_CAP
	update_site_config("orenzi_pos_plan", tier(data.get("features")))
	update_site_config("orenzi_pos_max_terminals", cap)


def _abbr(name: str) -> str:
	words = re.findall(r"[A-Za-z]+", name or "")
	abbr = "".join(w[0] for w in words).upper()[:5]
	if len(abbr) < 2:
		abbr = ("".join(words) or "SHOP").upper()[:3]
	return abbr if len(abbr) >= 2 else "SHOP"


def initialize(customer: dict) -> dict:
	"""For `execute` from the control plane: set up a new shop from the customer's details. Safe to run again: a
	site that already has its POS settings is left as it is."""
	from orenzi_pos.ops.provision import _owner, apply
	from orenzi_pos.ops.shop_spec import ShopSpecInvalid, parse_shop_spec

	frappe.set_user("Administrator")
	if frappe.db.get_single_value("POS Shop Settings", "company"):
		return {"site": frappe.local.site, "created": False}
	name = customer.get("name") or "Shop"
	gstin = (customer.get("gstin") or "").upper()
	address = ", ".join(
		x for x in (customer.get("address_line1"), customer.get("city"), customer.get("pincode")) if x
	)
	spec = {
		"site": frappe.local.site,
		"plan": "basic",  # the first signed snapshot sets the real tier
		"company": {"name": name, "abbr": _abbr(name)},
		"owner": {"full_name": customer.get("contact_name") or name, "email": customer.get("contact_email")},
		"shop": {
			"name": name,
			"address": address or customer.get("state") or name,
			"phone": customer.get("contact_mobile") or "",
			"gst_status": "registered" if gstin else "unregistered",
			"state_code": customer.get("state_code") or "",
			"gstin": gstin,
		},
		"tax_classes": DEFAULT_TAX_CLASSES,
	}
	try:
		shop = parse_shop_spec(spec)
	except ShopSpecInvalid as invalid:
		frappe.throw(f"The shop's details are not complete: {', '.join(invalid.reasons)}")
	apply(shop, setup_email=f"setup@{shop.site}")
	_owner(shop)  # the owner's sign-in; the control plane e-mails the password link
	frappe.db.set_single_value("System Settings", "setup_complete", 1)
	frappe.db.sql("update `tabInstalled Application` set is_setup_complete = 1")
	frappe.db.commit()
	return {"site": shop.site, "owner": shop.owner_email, "created": True}
