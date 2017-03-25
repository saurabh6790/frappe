# -*- coding: utf-8 -*-
# Copyright (c) 2017, Frappe Technologies and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document

class Webhook(Document):
	pass

def webhook_handler(doc, webhook_event):
	if not frappe.db.exists("DocType", "Webhook Service Event"):
		return

	for event in frappe.get_all("Webhook Service Event", filters={'document_name': doc.doctype,
		'document_event': webhook_event, 'enabled': 1}, fields=['name', 'parent', "resource_uri"]):

		frappe.enqueue('frappe.core.doctype.webhook.webhook.initiateREST', now=True, doc=doc,
			webhook_event=webhook_event, webhook=event.parent, resource_uri=event.resource_uri)

def initiateREST(doc, webhook_event, webhook, resource_uri):
	auth = prepare_auth(webhook)
	if not auth:
		return

	method = get_method(webhook_event)
	if method:
		method(resource_uri)

def prepare_auth(webhook):
	webhook = frappe.db.get_value("Webhook", webhook, ["username", "password", "client_key", "client_secret",
		"resource_owner_key", "resource_owner_secret", "enabled", "authentication_type"], as_dict=1)

	if not webhook.enabled:
		return None

	if webhook.authentication_type == "Basic Authentication":
		return (webhook.username, webhook.password)

def get_method(event):
	from frappe.integrations.utils import make_post_request, make_put_request, make_delete_request

	return {
		'Create': make_post_request,
		"Save": make_put_request,
		"Submit": make_put_request,
		"Cancel": make_put_request,
		"Delete": make_delete_request
	}[event]
