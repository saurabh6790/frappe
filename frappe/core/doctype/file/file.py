# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

from __future__ import unicode_literals
"""
record of files

naming for same name files: file.gif, file-1.gif, file-2.gif etc
"""

import frappe, frappe.utils
from frappe.utils.file_manager import delete_file_data_content
from frappe import _

from frappe.utils.nestedset import NestedSet

class File(NestedSet):
	nsm_parent_field = 'folder';
	no_feed_on_delete = True

	def before_insert(self):
		frappe.local.rollback_observers.append(self)
		self.set_folder_name()

	def after_insert(self):
		self.update_parent_folder_size()

	def validate(self):
		self.validate_duplicate_entry()
		self.validate_folder()
		self.set_folder_size()

	def set_folder_size(self):
		"""Set folder size if folder"""
		if self.is_folder:
			self.fize_size = self.get_folder_size()

			for folder in self.get_ancestors():
				frappe.db.set_value("File", folder, "file_size", self.get_folder_size(folder))

	def get_folder_size(self, folder=None):
		"""Returns folder size for current folder"""
		if not folder:
			folder = self.name
		return frappe.db.sql("""select sum(ifnull(file_size,0))
			from tabFile where folder=%s""", folder)[0][0]

	def set_folder_name(self):
		"""Make parent folders if not exists based on reference doctype and name"""
		if self.attached_to_doctype and not self.folder:
			self.folder = self.get_parent_folder_name()

	def update_parent_folder_size(self):
		"""Update size of parent folder"""
		if self.folder: # it not home
			frappe.get_doc("File", self.folder).save()

	def get_parent_folder_name(self):
		"""Returns parent folder name. If not exists, then make"""
		module_folder_name = self.get_module_folder_name()
		parent_folder_name = frappe.db.get_value("File", {"file_name": self.attached_to_doctype,
			"is_folder": 1, "folder": module_folder_name})
		if not parent_folder_name:
			# parent folder
			parent_folder = frappe.get_doc({
				"doctype": "File",
				"is_folder": 1,
				"file_name": _(self.attached_to_doctype),
				"folder": module_folder_name
			}).insert()

			parent_folder_name = parent_folder.name

		return parent_folder_name

	def get_module_folder_name(self):
		"""Returns module folder name. If not exists, then make"""
		if self.attached_to_doctype:
			module = frappe.db.get_value("DocType", self.attached_to_doctype, "module")

		home_folder_name = frappe.db.get_value("File", {"is_home_folder": 1})

		module_folder_name = frappe.db.get_value("File", {"file_name": module,
			"is_folder": 1, "folder": home_folder_name})

		if not module_folder_name:
			module_folder = frappe.get_doc({
				"doctype": "File",
				"is_folder": 1,
				"file_name": _(module),
				"folder": home_folder_name
			}).insert()

			module_folder_name = module_folder.name

		return module_folder_name


	def validate_folder(self):
		if not self.is_home_folder and not self.folder and \
			not self.flags.ignore_folder_validate:
			frappe.throw(_("Folder is mandatory"))

	def validate_duplicate_entry(self):
		if not self.flags.ignore_duplicate_entry_error:
			# check duplicate assignement
			n_records = frappe.db.sql("""select name from `tabFile`
				where content_hash=%s
				and name!=%s
				and attached_to_doctype=%s
				and attached_to_name=%s""", (self.content_hash, self.name, self.attached_to_doctype,
					self.attached_to_name))
			if len(n_records) > 0:
				self.duplicate_entry = n_records[0][0]
				frappe.throw(frappe._("Same file has already been attached to the record"), frappe.DuplicateEntryError)

	def on_trash(self):
		self.check_folder_is_empty()
		self.check_reference_doc_permission()
		super(File, self).on_trash()
		self.delete_file()
		self.update_parent_folder_size()

	def check_folder_is_empty(self):
		"""Throw exception if folder is not empty"""
		if frappe.get_all("File", {"folder": self.name}):
			frappe.throw(_("Folder {0} is not empty").format(self.name))

	def check_reference_doc_permission(self):
		"""Check if permission exists for reference document"""
		if self.attached_to_name:
			# check persmission
			try:
				if not self.flags.ignore_permissions and \
					not frappe.has_permission(self.attached_to_doctype,
						"write", self.attached_to_name):
					frappe.throw(frappe._("No permission to write / remove."),
						frappe.PermissionError)
			except frappe.DoesNotExistError:
				pass

	def delete_file(self):
		"""If file not attached to any other record, delete it"""
		if self.file_name and self.content_hash and (not frappe.db.count("File",
			{"content_hash": self.content_hash, "name": ["!=", self.name]})):
				delete_file_data_content(self)

	def on_rollback(self):
		self.on_trash()

def on_doctype_update():
	frappe.db.add_index("File", ["attached_to_doctype", "attached_to_name"])

def make_home_folder():
	frappe.get_doc({
		"doctype": "File",
		"is_folder": 1,
		"is_home_folder": 1,
		"file_name": _("Home")
	}).insert()

@frappe.whitelist()
def get_breadcrumbs(folder):
	"""returns name, file_name of parent folder"""
	lft, rgt = frappe.db.get_value("File", folder, ["lft", "rgt"])
	return frappe.db.sql("""select name, file_name from tabFile
		where lft < %s and rgt > %s order by lft asc""", (lft, rgt), as_dict=1)
