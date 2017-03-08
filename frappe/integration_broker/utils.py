# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
import json, urlparse
from frappe.utils import get_request_session
from frappe import _

def make_get_request(url, auth=None, data=None):
	if not auth:
		auth = ''
	if not data:
		data = {}

	try:
		s = get_request_session()
		frappe.flags.integration_request = s.get(url, data={}, auth=auth)
		frappe.flags.integration_request.raise_for_status()
		return frappe.flags.integration_request.json()

	except Exception, exc:
		frappe.log_error(frappe.get_traceback())
		raise exc

def make_post_request(url, auth=None, data=None):
	if not auth:
		auth = ''
	if not data:
		data = {}
	try:
		s = get_request_session()
		res = s.post(url, data=data, auth=auth)
		res.raise_for_status()

		if res.headers.get("content-type") == "text/plain; charset=utf-8":
			return urlparse.parse_qs(res.text)

		return res.json()
	except Exception, exc:
		frappe.log_error()
		raise exc

def create_request_log(data, integration_type, service_name, name=None):
	if isinstance(data, basestring):
		data = json.loads(data)

	integration_request = frappe.get_doc({
		"doctype": "Integration Request",
		"integration_type": integration_type,
		"integration_request_service": service_name,
		"reference_doctype": data.get("reference_doctype"),
		"reference_docname": data.get("reference_docname"),
		"data": json.dumps(data)
	})

	if name:
		integration_request.flags._name = name

	integration_request.insert(ignore_permissions=True)
	frappe.db.commit()

	return integration_request

def get_payment_gateway_controller(service_name):
	'''Return payment gateway controller'''
	try:
		return frappe.get_doc("{0} Settings".format(service_name))
	except Exception:
		frappe.throw(_("Module {service} not found".format(service=service_name)))

@frappe.whitelist(allow_guest=True, xss_safe=True)
def get_checkout_url(**kwargs):
	try:
		if kwargs.get('payment_gateway'):
			doc = frappe.get_doc("{0} Settings".format(kwargs.get('payment_gateway')))
			return doc.get_payment_url(**kwargs)
		else:
			raise Exception
	except Exception:
		frappe.respond_as_web_page(_("Something went wrong"),
			_("Looks like something is wrong with this site's payment gateway configuration. No payment has been made."),
			indicator_color='red',
			http_status_code=frappe.ValidationError.http_status_code)

