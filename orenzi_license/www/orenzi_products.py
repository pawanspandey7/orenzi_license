"""Add product page (/orenzi-products) on every Orenzi product site: the customer's own products, and a request
form for the others. The offers and prices come from the control plane (orenzi_license.products)."""

import frappe
from frappe.sessions import get_csrf_token

from orenzi_license import products

no_cache = 1

TEXT = {
	"en": {
		"title": "Orenzi products",
		"intro": "Your account's Orenzi products, and the others you can add. A new product starts as a free trial of {0} days; an Orenzi person checks every request and e-mails your account's contact when the new site is ready.",
		"yours": "Your products",
		"add": "Add a product",
		"plan": "Plan",
		"interval": "Billing after the trial",
		"monthly": "Monthly",
		"annual": "Yearly ({0} months free)",
		"submit": "Request a trial of {0}",
		"sending": "Sending…",
		"done": "Request sent. We will e-mail your account's contact when {0} is ready, usually within one working day.",
		"error": "Something went wrong. Please try again.",
		"nothing": "You already have every Orenzi product.",
		"blocked": "Please settle your current Orenzi bill before adding a product.",
		"not_allowed": "Only the people who manage this Orenzi account can add a product.",
		"not_wired": "This site is not connected to Orenzi's control plane, so products cannot be added from here.",
		"Trial Requested": "requested, waiting for approval",
		"Provisioning": "being set up",
		"Trial": "free trial",
		"Active": "active",
		"Past Due": "bill overdue",
		"Suspended": "suspended",
		"Cancelled": "cancelled",
		"Failed": "set-up failed, Orenzi is on it",
	},
	"hi": {
		"title": "Orenzi प्रोडक्ट",
		"intro": "आपके खाते के Orenzi प्रोडक्ट, और जो आप जोड़ सकते हैं। नया प्रोडक्ट {0} दिन के मुफ़्त ट्रायल से शुरू होता है; Orenzi की टीम हर अनुरोध जाँचती है और नई साइट तैयार होने पर आपके खाते के संपर्क को ईमेल करती है।",
		"yours": "आपके प्रोडक्ट",
		"add": "प्रोडक्ट जोड़ें",
		"plan": "प्लान",
		"interval": "ट्रायल के बाद भुगतान",
		"monthly": "मासिक",
		"annual": "वार्षिक ({0} महीने मुफ़्त)",
		"submit": "{0} का ट्रायल माँगें",
		"sending": "भेजा जा रहा है…",
		"done": "अनुरोध भेज दिया। {0} तैयार होने पर हम आपके खाते के संपर्क को ईमेल करेंगे, आमतौर पर एक कार्य-दिवस में।",
		"error": "कुछ गड़बड़ हुई। दोबारा कोशिश करें।",
		"nothing": "आपके पास सभी Orenzi प्रोडक्ट पहले से हैं।",
		"blocked": "प्रोडक्ट जोड़ने से पहले Orenzi का बकाया बिल चुका दें।",
		"not_allowed": "प्रोडक्ट सिर्फ़ वही लोग जोड़ सकते हैं जो इस Orenzi खाते को संभालते हैं।",
		"not_wired": "यह साइट Orenzi के कंट्रोल प्लेन से जुड़ी नहीं है, इसलिए यहाँ से प्रोडक्ट नहीं जोड़े जा सकते।",
		"Trial Requested": "अनुरोध भेजा, मंज़ूरी बाकी",
		"Provisioning": "तैयार हो रहा है",
		"Trial": "मुफ़्त ट्रायल",
		"Active": "चालू",
		"Past Due": "बिल बकाया",
		"Suspended": "रोका गया",
		"Cancelled": "बंद",
		"Failed": "सेट-अप में दिक्कत, Orenzi देख रहा है",
	},
	"mr": {
		"title": "Orenzi प्रॉडक्ट",
		"intro": "तुमच्या खात्याचे Orenzi प्रॉडक्ट, आणि जे तुम्ही जोडू शकता. नवीन प्रॉडक्ट {0} दिवसांच्या मोफत ट्रायलने सुरू होतो; Orenzi ची टीम प्रत्येक विनंती तपासते आणि नवीन साइट तयार झाल्यावर तुमच्या खात्याच्या संपर्काला ईमेल करते.",
		"yours": "तुमचे प्रॉडक्ट",
		"add": "प्रॉडक्ट जोडा",
		"plan": "प्लॅन",
		"interval": "ट्रायलनंतर पेमेंट",
		"monthly": "मासिक",
		"annual": "वार्षिक ({0} महिने मोफत)",
		"submit": "{0} ची ट्रायल मागा",
		"sending": "पाठवत आहे…",
		"done": "विनंती पाठवली. {0} तयार झाल्यावर आम्ही तुमच्या खात्याच्या संपर्काला ईमेल करू, साधारण एका कामकाजाच्या दिवसात.",
		"error": "काहीतरी चुकले. पुन्हा प्रयत्न करा.",
		"nothing": "तुमच्याकडे सर्व Orenzi प्रॉडक्ट आधीच आहेत.",
		"blocked": "प्रॉडक्ट जोडण्यापूर्वी Orenzi चे थकलेले बिल भरा.",
		"not_allowed": "प्रॉडक्ट फक्त हे Orenzi खाते सांभाळणारे लोकच जोडू शकतात.",
		"not_wired": "ही साइट Orenzi च्या कंट्रोल प्लेनशी जोडलेली नाही, त्यामुळे इथून प्रॉडक्ट जोडता येत नाहीत.",
		"Trial Requested": "विनंती पाठवली, मंजुरी बाकी",
		"Provisioning": "तयार होत आहे",
		"Trial": "मोफत ट्रायल",
		"Active": "सुरू",
		"Past Due": "बिल थकले",
		"Suspended": "थांबवले",
		"Cancelled": "बंद",
		"Failed": "सेट-अपमध्ये अडचण, Orenzi पाहत आहे",
	},
}
LANG_NAMES = {"en": "English", "hi": "हिन्दी", "mr": "मराठी"}


def page_lang() -> str:
	lang = frappe.form_dict.get("lang") or (frappe.local.lang or "en")[:2]
	return lang if lang in TEXT else "en"


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/orenzi-products"
		raise frappe.Redirect

	lang = page_lang()
	t = TEXT[lang]
	context.lang, context.t, context.lang_names = lang, t, LANG_NAMES
	context.problem, context.offers, context.trial_days = "", None, 14
	if not products.can_manage():
		context.problem = t["not_allowed"]
	elif not products.wired():
		context.problem = t["not_wired"]
	else:
		try:
			context.offers = products.get_offers(lang)
		except Exception:
			frappe.clear_messages()
			context.problem = t["error"]
	if context.offers:
		context.trial_days = context.offers.get("trial_days") or 14
		items = context.offers.get("products") or []
		context.mine = [p for p in items if p.get("status")]
		context.addable = [p for p in items if not p.get("status") and p.get("plans")]
		for p in context.mine:
			p["status_text"] = t.get(p["status"], p["status"])
		for p in context.addable:
			free = next((x["annual_months_free"] for x in p["plans"] if x.get("annual_months_free")), 2)
			p["annual_text"] = t["annual"].format(free)
			p["submit_text"] = t["submit"].format(p["name"])
	context.intro = t["intro"].format(context.trial_days)
	context.csrf_token = get_csrf_token()
	context.no_header = 1
	context.no_breadcrumbs = 1
	return context
