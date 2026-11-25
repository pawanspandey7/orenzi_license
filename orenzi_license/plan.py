"""Tenant-side plan gating, for every Orenzi product site.

The control plane (orenzi_saas) sends this site a signed snapshot of its plan: which features are on, the
limits, and the account status. The snapshot is HMAC-signed with a secret that lives only in site_config
(`orenzi_plan_secret`), so an admin who edits the Plan Snapshot row cannot grant themselves features.

    @frappe.whitelist()
    @requires_feature("events.ticketing")
    def sell_ticket(...): ...

    assert_within_limit("members", current=Person count, adding=1)

Policy when there is no valid snapshot: developer_mode sites allow everything (so local work is not blocked);
anywhere else only the products' core features work (hook `orenzi_core_features`). A Suspended / Cancelled
account, or one whose snapshot is older than valid_until plus GRACE_DAYS, becomes read-only: data is kept, writes
to the products' records (hooks `orenzi_read_only_modules`, `orenzi_read_only_doctypes`) are refused.

Club code imports this module as `orenzi_core.plan`; the control plane still calls it by that name too.
"""

import functools
import hashlib
import hmac
import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import get_datetime, now_datetime

GRACE_DAYS = 30
READ_ONLY_STATUSES = ("Suspended", "Cancelled")
SNAPSHOT_DOCTYPE = "Plan Snapshot"
# never made read-only: the control plane's own records (dev sites can carry both) and this app's
NEVER_READ_ONLY_MODULES = frozenset({"Orenzi SaaS", "Orenzi License"})
_UNSET = object()


class FeatureNotAvailable(frappe.PermissionError):
	pass


class LimitReached(frappe.ValidationError):
	pass


# ---- what the installed products declare ----------------------------------------------------------
def core_features() -> frozenset:
	"""Always available, even with no snapshot: each product's irreducible core."""
	return frozenset(frappe.get_hooks("orenzi_core_features") or [])


def _read_only_rules() -> tuple[frozenset, tuple, frozenset]:
	from orenzi_license.bridges import pos

	exact, prefixes = set(), []
	for pattern in [*(frappe.get_hooks("orenzi_read_only_modules") or []), *pos.read_only_modules()]:
		if pattern.endswith("*"):
			prefixes.append(pattern[:-1])
		else:
			exact.add(pattern)
	return frozenset(exact), tuple(prefixes), frozenset(frappe.get_hooks("orenzi_read_only_doctypes") or [])


def is_protected(doctype: str, module: str | None) -> bool:
	"""Whether read-only mode refuses writes to this doctype."""
	module = module or ""
	if module in NEVER_READ_ONLY_MODULES:
		return False
	exact, prefixes, doctypes = _read_only_rules()
	return doctype in doctypes or module in exact or module.startswith(prefixes)


# ---- signing (must stay byte-compatible with orenzi_saas.signing) ---------------------------------
def sign(secret: str, payload_text: str) -> str:
	return hmac.new(secret.encode(), payload_text.encode(), hashlib.sha256).hexdigest()


def verify(secret: str, payload_text: str, signature: str) -> dict | None:
	if not secret or not payload_text or not signature:
		return None
	if not hmac.compare_digest(sign(secret, payload_text), signature):
		return None
	try:
		data = json.loads(payload_text)
	except ValueError:
		return None
	return data if isinstance(data, dict) else None


# ---- receiving a snapshot -------------------------------------------------------------------------
def _stored() -> dict:
	rows = frappe.db.sql(
		"select field, value from `tabSingles` where doctype = %s and field in ('payload','signature','seq')",
		(SNAPSHOT_DOCTYPE,),
	)
	return dict(rows)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=60, seconds=3600)
def receive_plan(payload: str, signature: str):
	"""Called by the control plane. Anyone can reach it; only a correctly signed, newer snapshot is stored."""
	return store_plan(payload, signature)


def store_plan(payload: str, signature: str) -> dict:
	secret = frappe.conf.get("orenzi_plan_secret")
	data = verify(secret, payload, signature)
	if not data:
		frappe.throw(_("Invalid plan signature"), frappe.PermissionError)
	seq = int(data.get("seq") or 0)
	current = int(_stored().get("seq") or 0)
	if seq <= current:
		return {"ok": False, "reason": "stale", "seq": current}

	values = {
		"payload": payload,
		"signature": signature,
		"seq": seq,
		"plan": data.get("plan"),
		"status": data.get("status"),
		"valid_until": data.get("valid_until"),
		"received_at": now_datetime(),
	}
	for field, value in values.items():
		frappe.db.set_single_value(SNAPSHOT_DOCTYPE, field, value)
	frappe.local._orenzi_snapshot = _UNSET
	for path in frappe.get_hooks("orenzi_on_plan") or []:
		# a product that keeps its own copy of the plan (the POS app reads site_config) updates it here
		frappe.get_attr(path)(data)
	return {"ok": True, "seq": seq}


# ---- reading it -----------------------------------------------------------------------------------
def get_snapshot() -> dict | None:
	"""The verified snapshot, or None when there is none (or it fails verification)."""
	cached = getattr(frappe.local, "_orenzi_snapshot", _UNSET)
	if cached is not _UNSET:
		return cached
	stored = _stored()
	data = verify(frappe.conf.get("orenzi_plan_secret"), stored.get("payload"), stored.get("signature"))
	frappe.local._orenzi_snapshot = data
	return data


def _no_snapshot_allows(key: str) -> bool:
	"""With no plan from a control plane: a dev site allows everything, so does a staging or demo site whose config says
	`orenzi_all_features` (set by hand, never by the app), and anything else gets only the core. A signed snapshot, once
	installed, always decides instead."""
	return (
		bool(frappe.conf.developer_mode or frappe.conf.get("orenzi_all_features")) or key in core_features()
	)


def feature_enabled(key: str) -> bool:
	snap = get_snapshot()
	if snap is None:
		return _no_snapshot_allows(key)
	if key in core_features() and snap.get("status") not in READ_ONLY_STATUSES:
		return True
	return bool((snap.get("features") or {}).get(key, {}).get("enabled"))


def limit_value(key: str) -> int | None:
	"""The cap for `key`, or None for no cap (0 and missing both mean unlimited)."""
	snap = get_snapshot()
	if snap is None:
		return None
	value = (snap.get("limits") or {}).get(key)
	return int(value) if value else None


def is_read_only() -> bool:
	snap = get_snapshot()
	if snap is None:
		return False
	if snap.get("status") in READ_ONLY_STATUSES:
		return True
	valid_until = snap.get("valid_until")
	return bool(valid_until and now_datetime() > get_datetime(valid_until) + timedelta(days=GRACE_DAYS))


def requires_feature(key: str):
	def decorator(fn):
		@functools.wraps(fn)
		def wrapper(*args, **kwargs):
			if not feature_enabled(key):
				frappe.throw(
					_("Your plan does not include this feature ({0}). Upgrade to use it.").format(key),
					FeatureNotAvailable,
				)
			return fn(*args, **kwargs)

		return wrapper

	return decorator


def assert_within_limit(key: str, current: int, adding: int = 1) -> None:
	cap = limit_value(key)
	if cap is not None and current + adding > cap:
		frappe.throw(_("Your plan allows up to {0} {1}. Upgrade to add more.").format(cap, key), LimitReached)


# ---- read-only enforcement ------------------------------------------------------------------------
def block_writes_when_read_only(doc, method=None, *args, **kwargs):
	"""Wildcard validate / on_trash hook. Cheap for documents no product protects."""
	if not is_protected(doc.doctype, doc.meta.module):
		return
	if frappe.session.user == "Administrator" or frappe.flags.in_install or frappe.flags.in_migrate:
		return
	if is_read_only():
		frappe.throw(
			_("This account is read-only (plan suspended or expired). Your data is safe; renew to edit."),
			frappe.PermissionError,
		)


# ---- usage ----------------------------------------------------------------------------------------
def storage_usage() -> dict:
	storage = frappe.db.sql("select ifnull(sum(file_size), 0) from `tabFile`")[0][0] or 0
	return {"storage_mb": round(int(storage) / (1024 * 1024), 2)}


def collect_usage() -> dict:
	"""Numbers the control plane meters: what every installed product's collector reports, merged."""
	usage = {}
	for path in frappe.get_hooks("orenzi_usage_collectors") or []:
		try:
			usage.update(frappe.get_attr(path)() or {})
		except Exception:
			# one product's broken counter must not stop the others from being reported
			frappe.log_error(title=f"Orenzi usage collector {path} failed")
	return usage


def push_usage() -> bool:
	"""Daily job: report usage to the control plane if this site is wired to one."""
	import requests

	url = frappe.conf.get("orenzi_control_plane_url")
	secret = frappe.conf.get("orenzi_plan_secret")
	slug = frappe.conf.get("orenzi_tenant")
	if not (url and secret and slug):
		return False
	payload = json.dumps(
		{"tenant": slug, "usage": collect_usage(), "at": str(now_datetime())}, sort_keys=True
	)
	response = requests.post(
		f"{url.rstrip('/')}/api/method/orenzi_saas.api.report_usage",
		data={"payload": payload, "signature": sign(secret, payload)},
		timeout=15,
	)
	return response.ok
