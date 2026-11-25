"""What the control plane runs on a new product site, whatever the product (club site, POS, ...).

pilot -b <bench> frappe --site <site> execute orenzi_license.setup.configure --kwargs "{...}"
"""

import os
import re

import frappe

# a site config key the control plane may fill from its own secret store (e.g. the POS grant key)
SITE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{2,60}$")


def configure(tenant: str, control_plane_url: str = "", site_key_name: str = "") -> dict:
	"""Write this site's control-plane settings into site_config.json.

	Secrets come in environment variables rather than arguments, so they never appear in a process list or a log:
	ORENZI_PLAN_SECRET (the plan signing secret) and, when `site_key_name` is given, ORENZI_SITE_KEY (a product's
	own key, such as the POS grant key, stored under that name).
	"""
	from frappe.installer import update_site_config

	secret = os.environ.get("ORENZI_PLAN_SECRET")
	if not secret:
		frappe.throw("ORENZI_PLAN_SECRET is not set")
	update_site_config("orenzi_plan_secret", secret)
	update_site_config("orenzi_tenant", tenant)
	if control_plane_url:
		update_site_config("orenzi_control_plane_url", control_plane_url)
	if site_key_name:
		if not SITE_KEY_RE.match(site_key_name) or site_key_name.startswith(("db_", "orenzi_plan")):
			frappe.throw("Not a usable site key name")
		value = os.environ.get("ORENZI_SITE_KEY")
		if not value:
			frappe.throw("ORENZI_SITE_KEY is not set")
		update_site_config(site_key_name, value)
	return {"configured": True}


def login_link(admin_email: str) -> dict:
	"""A one-time link for the site's first administrator (or shop owner) to choose a password.

	A new site has no outgoing e-mail yet, so the control plane sends the link from its own account. Only the path is
	returned (the control plane knows the site's public address); Frappe stores just a hash of the key, and the link
	stops working once it has been used. Calling this again replaces the previous link.
	"""
	from urllib.parse import urlsplit

	frappe.set_user("Administrator")
	user = frappe.get_doc("User", admin_email)
	if not user.enabled or user.name in ("Administrator", "Guest"):
		frappe.throw("Not a site administrator")
	parts = urlsplit(user._reset_password(send_email=False))
	if not frappe.flags.in_test:
		frappe.db.commit()  # run from `bench execute`, which may not commit for us
	return {"path": f"{parts.path}?{parts.query}"}
