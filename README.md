# Orenzi License

The small agent every Orenzi product site carries: club sites, the POS, and later the WhatsApp API. It has no
dependency on any product.

- Receives the plan snapshot that the control plane (`app.orenzi.in`, app `orenzi_saas`) signs with the site's
  `orenzi_plan_secret`, and keeps it in the single *Plan Snapshot*.
- `feature_enabled`, `requires_feature`, `limit_value` and `assert_within_limit` gate features and limits.
- Makes the site read-only (no edits, no deletes) when the account is Suspended or Cancelled, or when the snapshot is
  30 days past `valid_until`.
- Pushes the site's usage to the control plane every day.

Each product says what is its own through hooks in its `hooks.py`:

```python
# features that work even with no snapshot
orenzi_core_features = ["members.registry", "directory.basic"]

# dotted paths; each returns {metric: number} and the results are merged
orenzi_usage_collectors = ["my_app.usage.collect"]

# what read-only mode protects: module names ("Orenzi *" matches by prefix) and doctypes
orenzi_read_only_modules = ["Orenzi *"]
orenzi_read_only_doctypes = ["Sales Invoice", "POS Invoice"]
```

Club code keeps importing `orenzi_core.plan`, which is this module under its old name.
