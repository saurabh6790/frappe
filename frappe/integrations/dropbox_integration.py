import frappe
from frappe import _
from frappe.integration_broker.integration_controller import IntegrationController
from frappe.utils import (cint, split_emails, get_request_site_address, cstr,
	get_files_path, get_backups_path, encode)
import os, json
from frappe.utils.backups import new_backup
from frappe.utils.background_jobs import enqueue

ignore_list = [".DS_Store"]

class Controller(IntegrationController):
	service_name = 'Dropbox Integration'
	parameters_template = [
		{
			"label": "App Access Key",
			'fieldname': 'app_access_key',
			'reqd': 1,
			'default': ''
		},
		{
			"label": "App Secret Key",
			'fieldname': 'app_secret_key',
			'reqd': 1,
			'default': ''
		},
		{
			"label": "Dropbox Access Key",
			'fieldname': 'dropbox_access_key',
			'reqd': 1,
			'default': '****'
		},
		{
			"label": "Dropbox Secret Key",
			'fieldname': 'dropbox_access_secret',
			'reqd': 1,
			'default': '****'
		}
	]
	
	custom_settings = [
		{
			"label": "Backup Frequency",
			"fieldname": "backup_frequency",
			"options": "\nDaily\nWeekly",
			"default": "",
			"reqd": 1,
			"fieldtype":'Select'
		}
	]
	

	js = "assets/frappe/js/dropbox_integration.js"

	scheduled_jobs = [
		{
			"daily_long": [
				"frappe.integrations.dropbox_integration.take_backups_daily"
			],
			"weekly_long": [
				"frappe.integrations.dropbox_integration.take_backups_weekly"
			]
		}
	]
	
	def enable(self, parameters, use_test_account=0):
		""" enable service """
		self.parameters = parameters
		self.validate_dropbox_credentails()

	def validate_dropbox_credentails(self):
		try:
			self.get_dropbox_session()
		except Exception, e:
			frappe.throw(e.message)

	def get_dropbox_session(self):
		try:
			from dropbox import session
		except:
			raise Exception(_("Please install dropbox python module"))

		parameters = self.get_parameters()
		if not (parameters["app_access_key"] or parameters["app_secret_key"]):
			raise Exception(_("Please set Dropbox access keys in your site config"))

		sess = session.DropboxSession(parameters["app_access_key"], parameters["app_secret_key"], "app_folder")

		return sess

#get auth token

@frappe.whitelist()
def get_dropbox_authorize_url():
	sess = Controller().get_dropbox_session()
	request_token = sess.obtain_request_token()

	setup_parameter({
		"dropbox_access_key": request_token.key,
		"dropbox_access_secret": request_token.secret
	})

	return_address = get_request_site_address(True) \
		+ "?cmd=frappe.integrations.dropbox_integration.dropbox_callback"

	url = sess.build_authorize_url(request_token, return_address)

	return {
		"url": url,
		"dropbox_access_key": request_token.key,
		"dropbox_access_secret": request_token.secret
	}

def setup_parameter(request_token):
	for key in ["dropbox_access_key", "dropbox_access_secret"]:
		for parameter in Controller().parameters:
			if key == parameter.fieldname:
				parameter.value = request_token[key]
				parameter.db_update()

	frappe.db.commit()

@frappe.whitelist(allow_guest=True)
def dropbox_callback(oauth_token=None, not_approved=False):
	parameters = Controller().get_parameters()
	if not not_approved:
		if parameters["dropbox_access_key"]==oauth_token:
			sess = Controller().get_dropbox_session()
			sess.set_request_token(parameters["dropbox_access_key"], parameters["dropbox_access_secret"])
			access_token = sess.obtain_access_token()

			setup_parameter({
				"dropbox_access_key": access_token.key,
				"dropbox_access_secret": access_token.secret
			})

			frappe.db.commit()
		else:
			frappe.respond_as_web_page(_("Dropbox Approval"), _("Illegal Access Token Please try again. <p>Please close this window.</p"),
				success=False, http_status_code=frappe.AuthenticationError.http_status_code)
	else:
		frappe.respond_as_web_page(_("Dropbox Approval"), _("Dropbox Access not approved. <p>Please close this window.</p"),
			success=False, http_status_code=frappe.AuthenticationError.http_status_code)

	frappe.respond_as_web_page(_("Dropbox Approval"), _("Dropbox access allowed. <p>Please close this window.</p"),
		success=False, http_status_code=frappe.AuthenticationError.http_status_code)

# backup process
@frappe.whitelist()
def take_backup():
	"Enqueue longjob for taking backup to dropbox"
	enqueue("frappe.integrations.dropbox_integration.take_backup_to_dropbox", queue='long')
	frappe.msgprint(_("Queued for backup. It may take a few minutes to an hour."))

def take_backups_daily():
	take_backups_if("Daily")

def take_backups_weekly():
	take_backups_if("Weekly")

def take_backups_if(freq):
	custom_settings_json = frappe.db.get_value("Dropbox Backup", None, "custom_settings_json")
	if custom_settings_json:
		custom_settings_json = json.loads(custom_settings_json)
		if custom_settings_json["backup_frequency"] == freq:
			take_backup_to_dropbox()

def take_backup_to_dropbox():
	did_not_upload, error_log = [], []
	try:
		if cint(frappe.db.get_value("Integration Service", "Dropbox Integration", "enabled")):
			did_not_upload, error_log = backup_to_dropbox()
			if did_not_upload: raise Exception

			send_email(True, "Dropbox")
	except Exception:
		file_and_error = [" - ".join(f) for f in zip(did_not_upload, error_log)]
		error_message = ("\n".join(file_and_error) + "\n" + frappe.get_traceback())
		frappe.errprint(error_message)
		send_email(False, "Dropbox", error_message)

def send_email(success, service_name, error_status=None):
	if success:
		subject = "Backup Upload Successful"
		message ="""<h3>Backup Uploaded Successfully</h3><p>Hi there, this is just to inform you
		that your backup was successfully uploaded to your %s account. So relax!</p>
		""" % service_name

	else:
		subject = "[Warning] Backup Upload Failed"
		message ="""<h3>Backup Upload Failed</h3><p>Oops, your automated backup to %s
		failed.</p>
		<p>Error message: <br>
		<pre><code>%s</code></pre>
		</p>
		<p>Please contact your system manager for more information.</p>
		""" % (service_name, error_status)

	if not frappe.db:
		frappe.connect()

	recipients = split_emails(frappe.db.get_value("Dropbox Backup", None, "send_notifications_to"))
	frappe.sendmail(recipients=recipients, subject=subject, message=message)

def backup_to_dropbox():
	if not frappe.db:
		frappe.connect()

	dropbox_client = get_dropbox_client()
	# upload database
	backup = new_backup(ignore_files=True)
	filename = os.path.join(get_backups_path(), os.path.basename(backup.backup_path_db))
	dropbox_client = upload_file_to_dropbox(filename, "/database", dropbox_client)

	frappe.db.close()

	# upload files to files folder
	did_not_upload = []
	error_log = []

	dropbox_client = upload_from_folder(get_files_path(), "/files", dropbox_client, did_not_upload, error_log)
	dropbox_client = upload_from_folder(get_files_path(is_private=1), "/private/files", dropbox_client, did_not_upload, error_log)

	frappe.connect()

	return did_not_upload, list(set(error_log))

def get_dropbox_client(previous_dropbox_client=None):
	from dropbox import client

	sess = Controller().get_dropbox_session()

	parameters = Controller().get_parameters()
	sess.set_token(parameters["dropbox_access_key"], parameters["dropbox_access_secret"])

	dropbox_client = client.DropboxClient(sess)

	# upgrade to oauth2
	token = dropbox_client.create_oauth2_access_token()
	dropbox_client = client.DropboxClient(token)
	if previous_dropbox_client:
		dropbox_client.connection_reset_count = previous_dropbox_client.connection_reset_count + 1
	else:
		dropbox_client.connection_reset_count = 0
	return dropbox_client

def upload_file_to_dropbox(filename, folder, dropbox_client):
	from dropbox import rest
	size = os.stat(encode(filename)).st_size

	with open(filename, 'r') as f:
		# if max packet size reached, use chunked uploader
		max_packet_size = 4194304

		if size > max_packet_size:
			uploader = dropbox_client.get_chunked_uploader(f, size)
			while uploader.offset < size:
				try:
					uploader.upload_chunked()
					uploader.finish(folder + "/" + os.path.basename(filename), overwrite=True)

				except rest.ErrorResponse, e:
					# if "[401] u'Access token not found.'",
					# it means that the user needs to again allow dropbox backup from the UI
					# so re-raise
					exc_message = cstr(e)
					if (exc_message.startswith("[401]")
						and dropbox_client.connection_reset_count < 10
						and exc_message != "[401] u'Access token not found.'"):


						# session expired, so get a new connection!
						# [401] u"The given OAuth 2 access token doesn't exist or has expired."
						dropbox_client = get_dropbox_client(dropbox_client)

					else:
						raise
		else:
			dropbox_client.put_file(folder + "/" + os.path.basename(filename), f, overwrite=True)

	return dropbox_client

def upload_from_folder(path, dropbox_folder, dropbox_client, did_not_upload, error_log):
	import dropbox.rest

	if not os.path.exists(path):
		return

	try:
		response = dropbox_client.metadata(dropbox_folder)
	except dropbox.rest.ErrorResponse, e:
		# folder not found
		if e.status==404:
			response = {"contents": []}
		else:
			raise

	for filename in os.listdir(path):
		filename = cstr(filename)

		if filename in ignore_list:
			continue

		found = False
		filepath = os.path.join(path, filename)
		for file_metadata in response["contents"]:
			if (os.path.basename(filepath) == os.path.basename(file_metadata["path"])
				and os.stat(encode(filepath)).st_size == int(file_metadata["bytes"])):
				found = True
				break

		if not found:
			try:
				dropbox_client = upload_file_to_dropbox(filepath, dropbox_folder, dropbox_client)
			except Exception:
				did_not_upload.append(filename)
				error_log.append(frappe.get_traceback())

	return dropbox_client
