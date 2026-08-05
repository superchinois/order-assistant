import streamlit as st
from utils.config_utils import init_odoo_cache, init_mongo_dao
from utils.function_utils import _map, nth, take, _filter, compose, _groupby
from utils.forecast_utils import odfilter
import utils.function_utils as od
import utils.mongo_utils as mu
import utils.forecast_utils as fu

import functools
import copy
import pandas as pd
from dateutil.relativedelta import relativedelta
import datetime as dt



st.title("Forecasts")

take_nth_eq = lambda x,y,z: compose(od._eq(z),nth(y), take(x))

_CACHE_TTL = 300  # 5 minutes


def load_raw_data():
    """Fetch all raw data from Odoo and Mongo. Independent of user choices.
    Cached in session_state so Streamlit reruns (widget toggles, expander expands)
    do not re-trigger network calls."""
    now = dt.datetime.now()
    cache = st.session_state.setdefault("_forecast_cache", {})

    if "raw_data" in cache:
        data, cached_at = cache["raw_data"]
        if (now - cached_at).total_seconds() < _CACHE_TTL:
            return data

    odoo_cache = init_odoo_cache()
    mongo_dao = init_mongo_dao()
    odoo_api = odoo_cache._api

    # STOCK
    squants   = fu.get_stock_quantities(odoo_api)
    filter_quants = functools.partial(fu.filter_stock_quants, odoo_cache, squants)
    s2_stock  = filter_quants(['s/s/2_'])
    s1_stock  = filter_quants(['s/s/1_'])
    ext_stock = filter_quants(['LGS','RDT', 'BAD'])

    # PURCHASES ORDERS
    recent_pos, po_items = fu.get_ordered_items(odoo_cache, '2026-01-01')

    # TRANSFERS
    create_date = dt.datetime(2026,1,1)
    transfers = fu.get_ext_wh_transfers(odoo_api, create_date)

    ordered    = set(_map(compose(nth(0), take('product_id')),_filter(od._and([take('id'), take('product_id')]), po_items)))
    transfered = set(_map(compose(nth(0), take('product_id')), transfers))

    # POS AND FUTURE ORDERS
    fromDate = mu.reset_to_midnight(dt.datetime.today()+relativedelta(days=-14))
    toDate   = mu.reset_to_midnight(dt.datetime.today()+relativedelta(days=1))
    pos_items    = fu.get_pos_items(mongo_dao, odoo_api , fromDate, toDate)
    future_items = fu.get_future_orders(odoo_api)

    pos_demands    = fu.compute_demands(pos_items, take('item_id'), 'quantity', odoo_cache.variants)
    future_demands = fu.compute_demands(future_items, compose(nth(0), take('product_template_id')), 'product_qty', odoo_cache.items)

    result = (s2_stock, s1_stock, ext_stock, ordered, transfered, pos_demands, future_demands, future_items)
    cache["raw_data"] = (result, now)
    return result


def compute_forecast(rows_type_str):
    """Compute sales and demands for the selected source.
    Cached per radio choice so switching back and forth is instant.
    Returns a deep copy so caller mutations don't pollute the cache."""
    now = dt.datetime.now()
    cache = st.session_state.setdefault("_forecast_cache", {})
    cache_key = f"forecast_{rows_type_str}"

    if cache_key in cache:
        data, cached_at = cache[cache_key]
        if (now - cached_at).total_seconds() < _CACHE_TTL:
            return copy.deepcopy(data)

    odoo_cache = init_odoo_cache()
    mongo_dao = init_mongo_dao()
    s2_stock, s1_stock, ext_stock, ordered, transfered, pos_demands, future_demands, future_items = load_raw_data()

    type_choices = ["Ventes passées", "Devis en cours"]
    items_demand = pos_demands if rows_type_str == type_choices[0] else future_demands

    sales   = fu.compute_historical_sales(mongo_dao, items_demand)
    demands = fu.compute_demand_rows(odoo_cache, items_demand, sales, [s2_stock, s1_stock, ext_stock], ordered, transfered)

    result = (demands, future_items)
    cache[cache_key] = (result, now)
    return copy.deepcopy(result)


type_choices = ["Ventes passées", "Devis en cours"]
frs_choices = ['Local', 'Import']
col1, col2 = st.columns(2)
with col1:
	rows_type = st.radio(
	    "Choisir la source des lignes",
	    type_choices,
	    index=0,
	)

with col2:
	frs_type = st.radio(
    "Fournisseurs",
    frs_choices,
    index=0,
	)

demands, future_items = compute_forecast(rows_type)

ratio_=.2
import_tag = 135
local_ou_import = lambda x: import_tag not in x
if frs_type==frs_choices[1]: # IMPORT
	local_ou_import = lambda x: import_tag in x

filters_obj = [
               [take('p_order'),od._eq(False)]
			   ,[take('category_id'), local_ou_import]
               ,[take('ratio'), od._gt(ratio_)]]
filtered_demands = fu.chain_filter(demands, filters_obj)
day_ratio = 1 - fu.compute_days_ratio(dt.datetime.today())
for fd in filtered_demands:
    fdsales = _map(lambda x: x[1] if len(x)>0 else 0,fd['sales'])
    base_sales = max(fd['avg_sales'], fdsales[1] if len(fdsales)>0 else 0)
    prev_sales = base_sales*day_ratio
    fd['proj_sales'] = prev_sales

understocked = odfilter(filtered_demands, [lambda x: x['ratio']>0.7 or x['stocks'][0] <=0 or x['stocks'][0]<x['proj_sales'] or x['proj_sales']==0])
s1_rescue = odfilter(filtered_demands, [lambda x: x['stocks'][0]<x['proj_sales'] and x['stocks'][1]>0])
by_suppliers = {}
for supplier, items in _groupby(understocked, take('cardname')):
    _items = list(items)
    by_suppliers[supplier] = _items



for s, items in sorted(by_suppliers.items(), key=lambda x: len(x[1]), reverse=True):
	with st.expander(f"{s} : {len(items)}"):
		for i in items:
			_itemid = i['itemid'][0]
			subh = f"{i['name']} # {i['itemcode']}, ID:{_itemid}{'ORDERED' if i['p_order'] else ''}{'TRANSFERED' if i['transfer'] else ''}"
			st.subheader(subh)
			st.dataframe([{k:v for k,v in zip(['s2', 's1', 'ext_wh'], i['stocks'])}])
			st.write('Projected sales: ',float(fu.to_2f(i['proj_sales'])), 'Moyenne', float(fu.to_2f(i['avg_sales'])))
			st.write(i['origin'], i['quantity'], 'Ratio',float(fu.to_2f(i['ratio'])))
			if i['origin']=='orders':
				with st.expander('commandes client'):
					order_rows = odfilter(future_items, [take_nth_eq('product_template_id', 0, _itemid)])
					st.dataframe(_map(od.get_values(['product_qty', 'order_partner_id.1','order_id.1']),order_rows))
			st.write(pd.DataFrame(i['sales'], columns=['mois', 'unit']))