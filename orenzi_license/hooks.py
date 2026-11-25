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
	}
}

scheduler_events = {
	"daily": ["orenzi_license.plan.push_usage"],
}

# what this app itself reports; products add their own (see README)
orenzi_usage_collectors = ["orenzi_license.plan.storage_usage"]
