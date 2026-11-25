"""The bridge between Orenzi's control plane and a WhatsApp API site (frappe_whatsapp + wa_inbox, greenadvise/WA-Inbox).

Every function does nothing unless `wa_inbox` is installed on the site. Owner's decisions (2026-11-26): each customer
has its own site; Orenzi's Meta account pays Meta, and the customer's bill carries a monthly subscription plus the
standard message fees.

- counts: what Meta itself marked billable, per day and per pricing category, from the `pricing` block wa_inbox keeps
  on each message's status webhook (`pricing_json`). The control plane bills them in arrears as Metered components
  `wa_<category>` (wa_marketing, wa_utility, wa_authentication, ...). The last few days are sent every day, so a
  missed push heals itself; a day's number simply replaces what was sent before.
- read-only: a Suspended or Cancelled site cannot send (or store) WhatsApp messages or change its inbox.
- a new site: its administrator's sign-in; the control plane e-mails the password link.
"""

import json
import re

import frappe
from frappe.utils import add_days, getdate, today

COUNT_DAYS = 3
READ_ONLY_MODULES = ("Frappe Whatsapp", "WA Inbox")
_CATEGORY_RE = re.compile(r"[^a-z0-9_]+")
INBOX_ROLES = ("WA Inbox Admin", "WA Inbox Supervisor", "WA Inbox Agent")
# a plan feature -> the WA Inbox Settings switches it allows; without the feature they are kept off
FEATURE_SWITCHES = {
	"wa.automation": ("auto_assign", "send_welcome_message", "send_away_message", "reassign_offline_chats"),
	"wa.csat": ("csat_enabled",),
	"wa.transcription": ("transcription_enabled",),
	"wa.ai": ("ai_enabled", "ai_intent_labels_enabled"),
}
SETTINGS = "WA Inbox Settings"


class UserLimitReached(frappe.ValidationError):
	pass


def installed() -> bool:
	return "wa_inbox" in frappe.get_installed_apps()


def usage() -> dict:
	"""The inbox's users (what the plan caps), as a count the site has now."""
	if not installed():
		return {}
	return {"users": len(_inbox_users())}


def _inbox_users(exclude: str | None = None) -> set:
	rows = frappe.db.sql(
		"""select distinct u.name from `tabUser` u join `tabHas Role` r on r.parent = u.name and r.parenttype = 'User'
		where u.enabled = 1 and r.role in %(roles)s and u.name not in ('Administrator', 'Guest')""",
		{"roles": INBOX_ROLES},
	)
	return {name for (name,) in rows if name != exclude}


def _snapshot():
	from orenzi_license import plan

	return plan.get_snapshot()


def _allowed(feature: str) -> bool:
	from orenzi_license import plan

	return plan.feature_enabled(feature)


def enforce_settings(doc, method=None) -> None:
	"""WA Inbox Settings validate: a switch the plan does not include stays off, and the broadcast and AI caps stay
	within the plan's limits. Without a snapshot (a dev site) nothing is forced."""
	if not installed() or _snapshot() is None:
		return
	for feature, fields in FEATURE_SWITCHES.items():
		if not _allowed(feature):
			for field in fields:
				if doc.meta.has_field(field):
					doc.set(field, 0)
	limits = _snapshot().get("limits") or {}
	for field, metric in (("broadcast_daily_cap", "broadcast_daily"), ("ai_daily_limit", "ai_daily")):
		cap = int(limits.get(metric) or 0)
		if cap and doc.meta.has_field(field) and (not doc.get(field) or int(doc.get(field)) > cap):
			doc.set(field, cap)
	if not _allowed("wa.broadcast") and doc.meta.has_field("broadcast_daily_cap"):
		doc.broadcast_daily_cap = 0


def check_user_limit(doc, method=None) -> None:
	"""User validate: giving someone an inbox role beyond the plan's `users` limit is refused."""
	if not installed() or doc.name in ("Administrator", "Guest") or not doc.enabled:
		return
	if not any(r.role in INBOX_ROLES for r in doc.get("roles") or []):
		return
	snap = _snapshot()
	cap = int(((snap or {}).get("limits") or {}).get("users") or 0)
	if cap and len(_inbox_users(exclude=doc.name)) + 1 > cap:
		frappe.throw(
			frappe._("Your plan allows up to {0} inbox users. Upgrade to add more.").format(cap),
			UserLimitReached,
		)


def on_plan(data: dict) -> None:
	"""After a new snapshot: save the inbox settings once, so enforce_settings switches off what the plan dropped."""
	if not installed() or not frappe.db.exists("DocType", SETTINGS):
		return
	frappe.get_single(SETTINGS).save(ignore_permissions=True)


def read_only_modules() -> tuple:
	return READ_ONLY_MODULES if installed() else ()


def metric_for(category: str) -> str | None:
	"""Meta's pricing category as a control-plane metric: 'marketing' -> 'wa_marketing'."""
	name = _CATEGORY_RE.sub("_", (category or "").strip().lower()).strip("_")
	return f"wa_{name}"[:40] if name else None


def daily_counts(days: int = COUNT_DAYS, on=None) -> dict:
	"""{'YYYY-MM-DD': {'wa_marketing': n, ...}} for the last `days` days up to and including today: outgoing
	messages Meta called billable, by the day they were sent."""
	if not installed():
		return {}
	end = getdate(on or today())
	start = add_days(end, -(days - 1))
	out = {str(add_days(start, i)): {} for i in range(days)}
	rows = frappe.db.sql(
		"""select date(creation) as day, pricing_json from `tabWhatsApp Message`
		where type = 'Outgoing' and ifnull(pricing_json, '') != ''
		and creation >= %s and creation < %s""",
		(start, add_days(end, 1)),
		as_dict=True,
	)
	for row in rows:
		try:
			pricing = json.loads(row.pricing_json) if isinstance(row.pricing_json, str) else row.pricing_json
		except ValueError:
			continue
		if not isinstance(pricing, dict) or not pricing.get("billable"):
			continue
		metric = metric_for(pricing.get("category") or "unknown")
		day = out.setdefault(str(row.day), {})
		day[metric] = day.get(metric, 0) + 1
	return out


def initialize(customer: dict) -> dict:
	"""For `execute` from the control plane: the customer's administrator on the new site. Safe to run again."""
	frappe.set_user("Administrator")
	email = (customer.get("contact_email") or "").strip().lower()
	if not email:
		frappe.throw("The customer has no contact e-mail")
	created = False
	if not frappe.db.exists("User", email):
		name = (customer.get("contact_name") or customer.get("name") or email).strip()
		first, _, last = name.partition(" ")
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first or name,
				"last_name": last,
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		)
		user.insert(ignore_permissions=True)
		roles = [r for r in ("System Manager", "WA Inbox Admin") if frappe.db.exists("Role", r)]
		user.add_roles(*roles)
		created = True
	frappe.db.set_single_value("System Settings", "setup_complete", 1)
	frappe.db.sql("update `tabInstalled Application` set is_setup_complete = 1")
	frappe.db.commit()
	return {"site": frappe.local.site, "admin": email, "created": created}
