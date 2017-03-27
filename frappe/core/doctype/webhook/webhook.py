# -*- coding: utf-8 -*-
# Copyright (c) 2017, Frappe Technologies and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document
import json

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
		doc.pop("modified")
		method(resource_uri.format(doc.name), auth=auth, data=json.dumps(doc))

def prepare_auth(webhook):
	webhook = frappe.get_doc("Webhook", webhook)

	if not webhook.enabled:
		return None
	
	descrept_secret(webhook)
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

def descrept_secret(doc):
	for field in doc.meta.fields:
		if field.fieldtype == "Password":
			doc.update({
				field.fieldname: doc.get_password(field.fieldname, raise_exception=False)
			})

