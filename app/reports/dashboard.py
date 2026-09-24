import streamlit as st
from streamlit_calendar import calendar
from utils.function_utils import _map, nth, take, _filter, compose, get_values
from utils.config_utils import init_odoo_cache, env_config
import utils.forecast_utils as fu
import datetime as dt
import pandas as pd
import functools
import itertools
from dateutil.relativedelta import relativedelta

st.title("Dashboard")


odoo_cache = init_odoo_cache()
odoo_api = odoo_cache._api

since_date_str='2026-01-01'
sort_partner_func=lambda x: x['partner_id'][0]
# PURCHASES ORDERS
recent_pos, po_items = fu.get_ordered_items(odoo_cache, since_date_str)

import_categ = 135
import_po=[]
local_po=[]
for o in recent_pos:
    partner_id = o['partner_id'][0]
    partner_categories = odoo_cache.partners.by_id(partner_id)['category_id']
    if import_categ in partner_categories:
        import_po.append(o)
    else:
        local_po.append(o)


_fmt="%Y-%m-%d"
today = dt.datetime.today().strftime(_fmt)

# Build calendar events from local purchase orders
calendar_events = []
for o in sorted(local_po, key=lambda x: x['date_planned']):
    po_values = get_values(['display_name','partner_id.1', 'date_planned', 'partner_ref', 'id', 'picking_type_id.1'])(o)
    arrival_day = po_values[2].split(' ')[0]
    po_id = po_values[4]
    partner_name = po_values[1]
    po_name = po_values[0]
    po_state = o.get('state', '')
    state_suffix = " (Brouillon)" if po_state == 'draft' else ""
    po_url = f"{env_config()['ODOO_URL']}/odoo/purchase/{po_id}?debug=1"

    if arrival_day < today:
        color = "#dc3545"   # red — late
    elif arrival_day == today:
        color = "#28a745"   # green — today
    else:
        color = "#6f42c1"   # violet — future

    calendar_events.append({
        "title": f"{po_name} - {partner_name}{state_suffix}",
        "start": arrival_day,
        "backgroundColor": color,
        "borderColor": color,
        "extendedProps": {
            "po_url": po_url,
            "display_name": po_values[0],
            "partner_name": partner_name,
            "state": po_state,
            "state_suffix": state_suffix,
            "partner_ref": po_values[3],
            "picking_type": po_values[5],
        }
    })

calendar_options = {
    "headerToolbar": {
        "left": "today prev,next",
        "center": "title",
#        "right": "listDay,listWeek,listMonth",
    },
    "initialView": "listMonth",
    "height": 700,
    "noEventsText": "Aucune commande locale",
    "listDayFormat": {"weekday": "long", "day": "numeric", "month": "long"},
    "listDaySideFormat": {"weekday": "long"},
}

custom_css = """
    .fc-event-past {
        opacity: 0.8;
    }
    .fc-event-title {
        font-weight: 700;
    }
    .fc-toolbar-title {
        font-size: 1.5rem;
    }
    .fc-list-event-title a {
        text-decoration: none;
        color: inherit;
    }
"""

st.subheader("Commandes d'achat locales")

if "clicked_url" in st.session_state and st.session_state["clicked_url"]:
    st.link_button(f"🔗 Ouvrir \"{st.session_state['clicked_title']}\" dans Odoo", st.session_state["clicked_url"])

cal = calendar(events=calendar_events, options=calendar_options, custom_css=custom_css, key="local_po_calendar")

if cal and cal.get("callback") == "eventClick":
    event = cal["eventClick"]["event"]
    props = event.get("extendedProps", {})
    new_url = props.get("po_url", "")
    if new_url and st.session_state.get("clicked_url") != new_url:
        st.session_state["clicked_url"] = new_url
        clicked_po = props.get("display_name", "")
        clicked_partner = props.get("partner_name", "")
        clicked_state_suffix = props.get("state_suffix", "")
        st.session_state["clicked_title"] = (
            f"{clicked_po} - {clicked_partner}{clicked_state_suffix}" if clicked_po else event.get("title", "")
        )
        st.rerun()