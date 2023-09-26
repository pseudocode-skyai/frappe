# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

# Search
from __future__ import unicode_literals

import json
import re

import wrapt
from six import string_types

import frappe
from frappe import _, is_whitelisted
from frappe.database.schema import SPECIAL_CHAR_PATTERN
from frappe.permissions import has_permission
from frappe.translate import get_translated_doctypes
from frappe.utils import cint, cstr, unique


def sanitize_searchfield(searchfield):
	if not searchfield:
		return

	if SPECIAL_CHAR_PATTERN.search(searchfield):
		frappe.throw(_("Invalid Search Field {0}").format(searchfield), frappe.DataError)


# this is called by the Link Field
@frappe.whitelist()
def search_link(
	doctype,
	txt,
	query=None,
	filters=None,
	# page_length=100,
	searchfield=None,
	reference_doctype=None,
	ignore_user_permissions=False,
):
	search_widget(
		doctype,
		txt.strip(),
		query,
		searchfield=searchfield,
		# page_length=page_length,
		filters=filters,
		reference_doctype=reference_doctype,
		ignore_user_permissions=ignore_user_permissions,
	)
	frappe.response["results"] = build_for_autosuggest(frappe.response["values"])
	del frappe.response["values"]


# this is called by the search box
@frappe.whitelist()
def search_widget(
    doctype,
    txt,
    query=None,
    searchfield=None,
    start=0,
    # page_length=100,
    filters=None,
    filter_fields=None,
    as_dict=False,
    reference_doctype=None,
    ignore_user_permissions=False,
):

    start = cint(start)

    if isinstance(filters, string_types):
        filters = json.loads(filters)

    if searchfield:
        sanitize_searchfield(searchfield)

    if not searchfield:
        searchfield = "name"
	
	# # Remove results where Customer is the filter value
	# if "Customer" in filters:
	# 	customer_filter_value = filters["Customer"]
	# 	intersection_results = [result for result in intersection_results if result != customer_filter_value]

    if not txt:  # If no search term, fetch all values
        results = frappe.get_all(
            doctype,
            filters=filters,
	    	page_length=20,
            fields=["name"],
            start=start,
            # limit_page_length=page_length,
            ignore_permissions=True,
        )
    else:
        # Split search term into words
        search_terms = txt.strip().split()
        # Initialize an empty set for intersection
        intersection_results = set()

        for term in search_terms:
            term_results = frappe.get_list(
                doctype,
                filters=filters,
                fields=["name"],
                or_filters=[
                    [doctype, searchfield, "like", "%{0}%".format(term)]
                ],
                limit_start=start,
                # limit_page_length=page_length,
                ignore_permissions=True,
            )
        
            term_results = {r.name for r in term_results}
            # frappe.msgprint(str(term_results))
            if not intersection_results:
                intersection_results = term_results
            else:
                # Intersect with previous results
                intersection_results &= term_results

        # Fetch full records based on intersection results
        results = frappe.get_list(
            doctype,
	    	page_length=20,
            filters={"name": ["in", list(intersection_results)]},
	        limit_start=start,
            # limit_page_length=page_length,
            order_by="name",
            ignore_permissions=True,
        )

    frappe.response["values"] = results


def get_std_fields_list(meta, key):
	# get additional search fields
	sflist = ["name"]
	if meta.search_fields:
		for d in meta.search_fields.split(","):
			if d.strip() not in sflist:
				sflist.append(d.strip())

	if meta.title_field and meta.title_field not in sflist:
		sflist.append(meta.title_field)

	if key not in sflist:
		sflist.append(key)

	return sflist

def build_for_autosuggest(res):
    results = []
    for r in res:
        out = {"value": r["name"], "description": ""}
        results.append(out)
    return results

def scrub_custom_query(query, key, txt):
	if "%(key)s" in query:
		query = query.replace("%(key)s", key)
	if "%s" in query:
		query = query.replace("%s", ((txt or "") + "%"))
	return query


def relevance_sorter(key, query, as_dict):
	value = _(key.name if as_dict else key[0])
	return (value.lower().startswith(query.lower()) is not True, value)


@wrapt.decorator
def validate_and_sanitize_search_inputs(fn, instance, args, kwargs):
	kwargs.update(dict(zip(fn.__code__.co_varnames, args)))
	sanitize_searchfield(kwargs["searchfield"])
	kwargs["start"] = cint(kwargs["start"])
	kwargs["page_len"] = cint(kwargs["page_len"])

	if kwargs["doctype"] and not frappe.db.exists("DocType", kwargs["doctype"]):
		return []

	return fn(**kwargs)


@frappe.whitelist()
def get_names_for_mentions(search_term):
	users_for_mentions = frappe.cache().get_value("users_for_mentions", get_users_for_mentions)
	user_groups = frappe.cache().get_value("user_groups", get_user_groups)

	filtered_mentions = []
	for mention_data in users_for_mentions + user_groups:
		if search_term.lower() not in mention_data.value.lower():
			continue

		mention_data["link"] = frappe.utils.get_url_to_form(
			"User Group" if mention_data.get("is_group") else "User Profile", mention_data["id"]
		)

		filtered_mentions.append(mention_data)

	return sorted(filtered_mentions, key=lambda d: d["value"])


def get_users_for_mentions():
	return frappe.get_all(
		"User",
		fields=["name as id", "full_name as value"],
		filters={
			"name": ["not in", ("Administrator", "Guest")],
			"allowed_in_mentions": True,
			"user_type": "System User",
			"enabled": True,
		},
	)


def get_user_groups():
	return frappe.get_all(
		"User Group", fields=["name as id", "name as value"], update={"is_group": True}
	)
