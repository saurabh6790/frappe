// Copyright (c) 2017, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on('Webhook', {
	refresh: function(frm) {
		frm.events.toggle_auth_params(frm)
	},

	authentication_type: function(frm){
		frm.events.toggle_auth_params(frm)
	},
	
	toggle_auth_params: function(frm){
		frm.toggle_display(["username", "password"], frm.doc.authentication_type=='Basic Authentication')
		frm.toggle_display(["client_key", "client_secret", "resource_owner_key", "resource_owner_secret"],
			frm.doc.authentication_type=='OAuth 1')
	}
	
});
