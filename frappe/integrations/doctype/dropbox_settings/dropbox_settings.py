# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
import os
from frappe import _
from frappe.model.document import Document
import dropbox
from frappe.utils.backups import new_backup
from frappe.utils.background_jobs import enqueue
from frappe.utils import (cint, split_emails, get_request_site_address, cstr,
	get_files_path, get_backups_path, encode)

ignore_list = [".DS_Store"]

class DropboxSettings(Document):
	def onload(self):
		if not self.app_access_key and frappe.conf.dropbox_access_key:
			self.dropbox_setup_via_site_config = 1

@frappe.whitelist()
def take_backup():
	"Enqueue longjob for taking backup to dropbox"
	enqueue("frappe.integrations.doctype.dropbox_settings.dropbox_settings.take_backup_to_dropbox", queue='long', timeout=1500)
	frappe.msgprint(_("Queued for backup. It may take a few minutes to an hour."))

def take_backups_daily():
	take_backups_if("Daily")

def take_backups_weekly():
	take_backups_if("Weekly")

def take_backups_if(freq):
	if frappe.db.get_value("Dropbox Settings", None, "backup_frequency") == freq:
		take_backup_to_dropbox()

def take_backup_to_dropbox():
	did_not_upload, error_log = [], []
	try:
		if cint(frappe.db.get_value("Dropbox Settings", None, "enabled")):
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

	recipients = split_emails(frappe.db.get_value("Dropbox Settings", None, "send_notifications_to"))
	frappe.sendmail(recipients=recipients, subject=subject, message=message)

def backup_to_dropbox():
	if not frappe.db:
		frappe.connect()

	# upload database
	dropbox_settings = get_dropbox_settings()
	if not dropbox_settings['access_token']:
		return

	dropbox_client = dropbox.Dropbox(dropbox_settings['access_token'])
	backup = new_backup(ignore_files=True)
	filename = os.path.join(get_backups_path(), os.path.basename(backup.backup_path_db))
	upload_file_to_dropbox(filename, "/database", dropbox_client)

	frappe.db.close()
	
	# upload files to files folder
	did_not_upload = []
	error_log = []

	upload_from_folder(get_files_path(), "/files", dropbox_client, did_not_upload, error_log)
	upload_from_folder(get_files_path(is_private=1), "/private/files", dropbox_client, did_not_upload, error_log)

	frappe.connect()
	return did_not_upload, list(set(error_log))

def upload_from_folder(path, dropbox_folder, dropbox_client, did_not_upload, error_log):
	if not os.path.exists(path):
		return

	try:
		response = dropbox_client.files_list_folder(dropbox_folder)
	except dropbox.exceptions.ApiError as e:
		# folder not found
		if isinstance(e.error, dropbox.files.ListFolderError):
			response = frappe._dict({"entries": []})
		else:
			raise

	for filename in os.listdir(path):
		filename = cstr(filename)

		if filename in ignore_list:
			continue

		found = False
		filepath = os.path.join(path, filename)
		for file_metadata in response.entries:
			if (os.path.basename(filepath) == file_metadata.name
				and os.stat(encode(filepath)).st_size == int(file_metadata.size)):
				found = True
				break

		if not found:
			try:
				upload_file_to_dropbox(filepath, dropbox_folder, dropbox_client)
			except Exception:
				did_not_upload.append(filename)
				error_log.append(frappe.get_traceback())

def upload_file_to_dropbox(filename, folder, dropbox_client):
	create_folder_if_not_exists(folder, dropbox_client)
	chunk_size = 4 * 1024 * 1024
	file_size = os.path.getsize(filename)
	mode = (dropbox.files.WriteMode.overwrite)

	f = open(encode(filename), 'rb')
	path = "{0}/{1}".format(folder, os.path.basename(filename))

	if file_size <= chunk_size:
		dropbox_client.files_upload(f.read(), path, mode)
	else:
		upload_session_start_result = dropbox_client.files_upload_session_start(f.read(chunk_size))
		cursor = dropbox.files.UploadSessionCursor(session_id=upload_session_start_result.session_id, offset=f.tell())
		commit = dropbox.files.CommitInfo(path=path, mode=mode)

		while f.tell() < file_size:
			if ((file_size - f.tell()) <= chunk_size):
				dropbox_client.files_upload_session_finish(f.read(chunk_size), cursor, commit)
			else:
				dropbox_client.files_upload_session_append(f.read(chunk_size), cursor.session_id,cursor.offset)
				cursor.offset = f.tell()

def create_folder_if_not_exists(folder, dropbox_client):
	try:
		dropbox_client.files_get_metadata(folder)
	except dropbox.exceptions.ApiError as e:
		# folder not found
		if isinstance(e.error, dropbox.files.GetMetadataError):
			dropbox_client.files_create_folder(folder)
		else:
			raise

def get_dropbox_settings(redirect_uri=False):
	settings = frappe.get_doc("Dropbox Settings")
	app_details = {
		"app_key": settings.app_access_key or frappe.conf.dropbox_access_key,
		"app_secret": settings.get_password(fieldname="app_secret_key", raise_exception=False)
			if settings.app_secret_key else frappe.conf.dropbox_secret_key,
		'access_token': settings.get_password('dropbox_access_token', raise_exception=False)
			if settings.dropbox_access_token else ''
	}

	if redirect_uri:
		app_details.update({
			'rediret_uri': get_request_site_address(True) \
				+ '/api/method/frappe.integrations.doctype.dropbox_settings.dropbox_settings.dropbox_auth_finish' \
				if settings.app_secret_key else frappe.conf.dropbox_rediret_uri,
		})

	if not app_details['app_key'] or not app_details['app_secret']:
		raise Exception(_("Please set Dropbox access keys in your site config"))

	return app_details

@frappe.whitelist()
def get_dropbox_authorize_url():
	app_details = get_dropbox_settings(redirect_uri=True)
	dropbox_oauth_flow = dropbox.DropboxOAuth2Flow(
		app_details["app_key"],
		app_details["app_secret"],
		app_details["rediret_uri"],
		{},
		"dropbox-auth-csrf-token"
	)

	auth_url = dropbox_oauth_flow.start()
	return {"auth_url": auth_url}

@frappe.whitelist()
def dropbox_auth_finish():
	app_details = get_dropbox_settings(redirect_uri=True)
	callback = frappe.form_dict
	close = '<p class="text-muted">' + _('Please close this window') + '</p>'

	dropbox_oauth_flow = dropbox.DropboxOAuth2Flow(
		app_details["app_key"],
		app_details["app_secret"],
		app_details["rediret_uri"],
		{'dropbox-auth-csrf-token': callback.state},
		"dropbox-auth-csrf-token"
	)

	if callback.state or callback.code:
		token = dropbox_oauth_flow.finish({'state': callback.state, 'code': callback.code})
		frappe.db.set_value("Dropbox Settings", None, 'dropbox_access_token', token.access_token)
		frappe.db.commit()
	else:
		frappe.respond_as_web_page(_("Dropbox Setup"),
			_("Illegal Access Token. Please try again") + close,
			indicator_color='red',
			http_status_code=frappe.AuthenticationError.http_status_code)

	frappe.respond_as_web_page(_("Dropbox Setup"),
		_("Dropbox access is approved!") + close,
		indicator_color='green')
