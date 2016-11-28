# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies and contributors
# For license information, please see license.txt

"""
# Integrating RazorPay

### Validate Currency

Example:

	from frappe.integration_broker.doctype.integration_service.integration_service import get_integration_controller

	controller = get_integration_controller("Razorpay")
	controller().validate_transaction_currency(currency)

### 2. Redirect for payment

Example:

	payment_details = {
		"amount": 600,
		"title": "Payment for bill : 111",
		"description": "payment via cart",
		"reference_doctype": "Payment Request",
		"reference_docname": "PR0001",
		"payer_email": "NuranVerkleij@example.com",
		"payer_name": "Nuran Verkleij",
		"order_id": "111",
		"currency": "INR"
	}

	# Redirect the user to this url
	url = controller().get_payment_url(**payment_details)


### 3. On Completion of Payment

Write a method for `on_payment_authorized` in the reference doctype

Example:

	def on_payment_authorized(payment_status):
		# this method will be called when payment is complete


##### Notes:

payment_status - payment gateway will put payment status on callback.
For razorpay payment status is Authorized

"""

from __future__ import unicode_literals
import frappe
from frappe.utils import get_url, call_hook_method, cint
from frappe import _
import urllib, json
from frappe.integration_broker.doctype.integration_service.integration_service import IntegrationService

class RazorpaySettings(IntegrationService):
	service_name = "Razorpay"
	supported_currencies = ["INR"]

	scheduler_events = {
		"all": [
			"frappe.integrations.doctype.razorpay_settings.razorpay_settings.capture_payment"
		]
	}

	def validate(self):
		if not self.flags.ignore_mandatory:
			self.validate_razorpay_credentails()

	def on_update(self):
		pass

	def enable(self):
		call_hook_method('payment_gateway_enabled', gateway='Razorpay')

		if not self.flags.ignore_mandatory:
			self.validate_razorpay_credentails()

	def validate_razorpay_credentails(self):
		if self.api_key and self.api_secret:
			try:
				self.get_request(url="https://api.razorpay.com/v1/payments",
					auth=(self.api_key, self.get_password(fieldname="api_secret", raise_exception=False)))
			except Exception:
				frappe.throw(_("Seems API Key or API Secret is wrong !!!"))

	def validate_transaction_currency(self, currency):
		if currency not in self.supported_currencies:
			frappe.throw(_("Please select another payment method. {0} does not support transactions in currency '{1}'").format(self.service_name, currency))

	def get_payment_url(self, **kwargs):
		return get_url("./integrations/razorpay_checkout?{0}".format(urllib.urlencode(kwargs)))

	def create_request(self, data):
		self.data = frappe._dict(data)

		try:
			self.integration_request = super(RazorpaySettings, self).create_request(self.data, "Host", \
				"Razorpay")
			return self.authorize_payment()

		except Exception:
			frappe.log_error(frappe.get_traceback())
			return{
				"redirect_to": frappe.redirect_to_message(_('Server Error'), _("Seems issue with server's razorpay config. Don't worry, in case of failure amount will get refunded to your account.")),
				"status": 401
			}

	def authorize_payment(self):
		"""
		An authorization is performed when user’s payment details are successfully authenticated by the bank.
		The money is deducted from the customer’s account, but will not be transferred to the merchant’s account
		until it is explicitly captured by merchant.
		"""
		data = json.loads(self.integration_request.data)

		settings = self.get_settings(data)
		redirect_to = data.get('notes', {}).get('redirect_to') or None
		redirect_message = data.get('notes', {}).get('redirect_message') or None

		try:
			resp = self.get_request("https://api.razorpay.com/v1/payments/{0}"
				.format(self.data.razorpay_payment_id), auth=(settings.api_key,
					settings.api_secret))

			if resp.get("status") == "authorized":
				self.integration_request.db_set('status', 'Authorized', update_modified=False)
				self.flags.status_changed_to = "Authorized"

			else:
				frappe.log_error(str(resp), 'Razorpay Payment not authorized')

		except:
			frappe.log_error(frappe.get_traceback())
			# failed
			pass

		status = frappe.flags.integration_request.status_code

		if self.flags.status_changed_to == "Authorized":
			if self.data.reference_doctype and self.data.reference_docname:
				custom_redirect_to = None
				try:
					custom_redirect_to = frappe.get_doc(self.data.reference_doctype,
						self.data.reference_docname).run_method("on_payment_authorized", self.flags.status_changed_to)
				except Exception:
					frappe.log_error(frappe.get_traceback())

				if custom_redirect_to:
					redirect_to = custom_redirect_to

			redirect_url = 'payment-success'
		else:
			redirect_url = 'payment-failed'

		if redirect_to:
			redirect_url += '?' + urllib.urlencode({'redirect_to': redirect_to})
		if redirect_message:
			redirect_url += '&' + urllib.urlencode({'redirect_message': redirect_message})

		return {
			"redirect_to": redirect_url,
			"status": status
		}

	def get_settings(self, data):
		settings = frappe._dict({
			"api_key": self.api_key,
			"api_secret": self.get_password(fieldname="api_secret", raise_exception=False)
		})

		if cint(data.get('notes', {}).get('use_sandbox')):
			settings.update({
				"api_key": frappe.conf.sandbox_api_key,
				"api_secret": frappe.conf.sandbox_api_secret,
			})

		return settings

def capture_payment(is_sandbox=False, sanbox_response=None):
	"""
		Verifies the purchase as complete by the merchant.
		After capture, the amount is transferred to the merchant within T+3 days
		where T is the day on which payment is captured.

		Note: Attempting to capture a payment whose status is not authorized will produce an error.
	"""
	controller = frappe.get_doc("Razorpay Settings")

	for doc in frappe.get_all("Integration Request", filters={"status": "Authorized",
		"integration_request_service": "Razorpay"}, fields=["name", "data"]):
		try:
			if is_sandbox:
				resp = sanbox_response
			else:
				data = json.loads(doc.data)
				settings = controller.get_settings(data)

				resp = controller.post_request("https://api.razorpay.com/v1/payments/{0}/capture".format(data.get("razorpay_payment_id")),
					auth=(settings.api_key, settings.api_secret), data={"amount": data.get("amount")})

			if resp.get("status") == "captured":
				frappe.db.set_value("Integration Request", doc.name, "status", "Completed")

		except Exception:
			doc = frappe.get_doc("Integration Request", doc.name)
			doc.status = "Failed"
			doc.error = frappe.get_traceback()
			frappe.log_error(doc.error, '{0} Failed'.format(doc.name))

@frappe.whitelist(allow_guest=True, xss_safe=True)
def get_checkout_url(**kwargs):
	try:
		return frappe.get_doc("Razorpay Settings").get_payment_url(**kwargs)
	except Exception:
		frappe.respond_as_web_page(_("Something went wrong"),
			_("Looks like something is wrong with this site's Razorpay configuration. Don't worry! No payment has been made."),
			success=False,
			http_status_code=frappe.ValidationError.http_status_code)

@frappe.whitelist()
def get_service_details():
	return """
		<div>
			<p> Steps to configure Service
			<ol>
				<li> Get Razorpay api credentials by login to:
					<a href="https://razorpay.com/" target="_blank">
						https://razorpay.com/
					</a>
				</li>
				<br>
				<li> Setup credentials on Razorpay Settings doctype.
					Click on
					<button class="btn btn-default btn-xs disabled"> Razorpay Settings </button>
					top right corner
				</li>
				<br>
				<li>
					After saving settings,
						<label>
							<span class="input-area">
								<input type="checkbox" class="input-with-feedback" checked disabled>
							</span>
							<span class="label-area small">Enable</span>
						</label>
					Razorpay Integration Service and Save a document.
				</li>
				<br>
				<li>
					To view Razorpays payment logs,
					<button class="btn btn-default btn-xs disabled"> Show Log </button>
				</li>
			</ol>
		</div>
	"""