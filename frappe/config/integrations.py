from __future__ import unicode_literals
from frappe import _

def get_data():
	return [
		{
			"label": _("Setup"),
			"icon": "icon-star",
			"items": [
				{
					"type": "doctype",
					"name": "Social Login Keys",
					"description": _("Enter keys to enable login via Facebook, Google, GitHub."),
				},
				{
					"type": "doctype",
					"name": "Dropbox Backup",
					"description": _("Manage cloud backups on Dropbox"),
					"hide_count": True
				},
				{
					"type": "doctype",
					"name": "Shopify Settings",
					"description": _("Connect Shopify with ERPNext"),
					"hide_count": True
				}
			]
		}
	]
