app_name = "orenzi_license"
app_title = "Orenzi License"
app_publisher = "GreenAdvise Technologies Private Limited"
app_description = "Orenzi licence agent: signed plan, feature gates, read-only on suspension, usage reports"
app_email = "dev@orenzi.example"
app_license = "gpl-3.0"

required_apps = []

doc_events = {
	"*": {
		"validate": "orenzi_license.plan.block_writes_when_read_only",
		"on_trash": "orenzi_license.plan.block_writes_when_read_only",
	},
	# the WhatsApp plan's switches and user cap (bridges/wa.py); these doctypes exist only where wa_inbox is
	"WA Inbox Settings": {"validate": "orenzi_license.bridges.wa.enforce_settings"},
	"User": {"validate": "orenzi_license.bridges.wa.check_user_limit"},
}

scheduler_events = {
	"daily": ["orenzi_license.plan.push_usage"],
}

# what this app itself reports; products add their own (see README). The POS bridge reports nothing unless the
# site has orenzi_pos (bridges/pos.py).
orenzi_usage_collectors = [
	"orenzi_license.plan.storage_usage",
	"orenzi_license.bridges.pos.usage",
	"orenzi_license.bridges.wa.usage",
]
orenzi_on_plan = ["orenzi_license.bridges.pos.on_plan", "orenzi_license.bridges.wa.on_plan"]
# per-day counts (WhatsApp messages Meta billed); empty unless the site has wa_inbox (bridges/wa.py)
orenzi_daily_counters = ["orenzi_license.bridges.wa.daily_counts"]

# the Add product page (www/orenzi-products, products.py) in the desk's user menu; the page itself checks who may
# use it (System Managers and the products' `orenzi_account_roles`)
standard_navbar_items = [
	{
		"item_label": "Orenzi products",
		"item_type": "Route",
		"route": "/orenzi-products",
		"condition": "frappe.user.has_role('System Manager')",
		"is_standard": 1,
	}
]
