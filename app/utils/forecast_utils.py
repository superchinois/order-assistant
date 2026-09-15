from .function_utils import _map, _filter, build_fields, merge_into, flatten
from .function_utils import  id_in, nth, take, index_on_id, compose
from utils.mongo_utils import compute_months_dict_betweenDates, reset_to_midnight
from dateutil.relativedelta import relativedelta
from dotenv import dotenv_values
from collections import namedtuple
import utils.function_utils as od
import functools
import os
import pandas as pd
import datetime as dt
import numpy as np
import itertools


def build_odoo_all_conditions(domains):
    domains_count = len(domains)
    if domains_count <= 1:
        return domains
    else :
        return ["&"]*(domains_count - 1) + domains

def odfilter(*args, **kwargs):
	filters = args[1].copy()
	return od._filter_(args[0], filters)

def chain_filter(data, filters_array):
	return functools.reduce(lambda x,y: odfilter(x,y), filters_array, data)

### CHECK ITEMS AVAILABILITY FROM SALE ORDER

so_fields  = build_fields("""carrier_id
date_order
order_line
partner_id""")

def any_startswith(values):
	def _test_value(name):
		return any(map(lambda v: name.startswith(v),values))
	return _test_value

def filter_stock_quants(odoo_cache, quants, locations):
	sort_by_pid = compose(nth(0), take('product_id'))
	sum_quantity = lambda q: functools.reduce(lambda x,y: x+y['quantity'], q, 0)
	filtered_quants =  odfilter(quants, [take('location_id'), nth(1), any_startswith(locations)])
	sstock = {k:v for k,v in _map(lambda x: [odoo_cache.variants.by_id(x[0])['id'], sum_quantity(x[1])],
							od._groupby(filtered_quants, sort_by_pid))}
	return sstock

def get_bin_by_thresholds(demands):
	# demands is of shape (int, list)
	import bisect
	thresholds = [0.2, 0.5,0.8, 1]
	cut_indexes=[]
	demands_count = len(demands)
	ratio_array = _map(take('ratio'), demands)
	for t in thresholds:
		cut_indexes.append(bisect.bisect_left(ratio_array, t))
	# insert start and end
	if 0 not in cut_indexes:
		cut_indexes = [0]+cut_indexes
	if demands_count not in cut_indexes:
		cut_indexes = cut_indexes+[demands_count]
	return cut_indexes
	
def get_stock_quantities(odoo_api):
	sq_fields=["id", "inventory_quantity", "location_id", "lot_id", "on_hand", "package_id", "product_id", "product_reference_code",
		  "quantity", "product_uom_id", "inventory_quantity_set", "warehouse_id"]
	#sq_domain=eq_("warehouse_id", 1) # Entrepot SIS
	squants = odoo_api.extract_from_odoo("stock.quant", [], sq_fields)
	return squants
	
def get_future_orders(odoo_api):
	sorderline_fields = build_fields("""order_id
order_partner_id
product_template_id
product_packaging_qty
product_qty
product_uom_qty
qty_available_today
sequence""")
	past_ten_days=-10
	ten_days_ago = dt.datetime.combine(dt.datetime.today() + dt.timedelta(days = past_ten_days)
									   , dt.time(0, 0, 0)).strftime("%Y-%m-%d %H:%M:%S")
	so_domain=["&", ("pos_order_line_ids", "=", False), 
"&", ("delivery_status", "!=", "full"), 
"&", ("state", "!=", "cancel"), 
"&", ("amount_total", ">", 0), 
"&", ("partner_id.category_id", "in", [166, 109]), 
("create_date", ">=", ten_days_ago)]
	so_fields  = build_fields("""carrier_id
date_order
order_line
partner_id""")
	orders = odoo_api.extract_from_odoo('sale.order', so_domain, so_fields)
	orderlines = odoo_api.extract_from_odoo('sale.order.line', id_in(flatten(_map(take('order_line'), orders))),sorderline_fields)
	orderlines = _filter(take('product_template_id'), orderlines)
	return orderlines
	
def get_pos_items(mongo_dao, odoo_api, fromDate, toDate):
	def get_stock_moves_from(odoo_api, location_id, start_date, end_date_excluded):
		start_str = start_date.strftime("%Y-%m-%d %H:%M:%S") if isinstance(start_date, dt.datetime) else start_date
		end_str = end_date_excluded.strftime("%Y-%m-%d %H:%M:%S") if isinstance(end_date_excluded, dt.datetime) else end_date_excluded
		sm_domain=['&','&',
		 ['date_done', '>=', start_str],['date_done', '<', end_str],
		 '|',['location_dest_id', '=', location_id],['location_id', '=', location_id]]
		stock_pickings = odoo_api.extract_from_odoo('stock.picking', sm_domain, ['partner_id','picking_type_id', 'date_done'])
		return stock_pickings
	pos_demands = odfilter(get_stock_moves_from(odoo_api, 5, fromDate, toDate), [take('picking_type_id'), nth(0), od._eq(9)])
	pos_items = mongo_dao.find_query({'$and': [{"docnum":{"$in": _map(take('id'),pos_demands)}}, {"docdate":{"$gte":fromDate}}, {"docdate":{"$lte": toDate}}]})
	return pos_items.to_dict(orient='records')


def compute_sales_summaries(mongo_dao, over_demand, fromDate, toDate):
	def monthly_stock_moves(itemcodes, from_date: dt.datetime, to_date: dt.datetime):
		pipeline = [
			{"$match":{"$and": [{"item_id":{"$in": itemcodes}}, {"docdate":{"$gte":from_date}}, {"docdate":{"$lte":to_date}}]}},
			{"$project":{'item_id':1,"quantity":1,"timestamp":{"$dateToString": {"format":"%Y-%m", "date":"$docdate"}}}},
			{"$group": { "_id":{'item_id': '$item_id', 'timestamp': '$timestamp'}, "quantity": { "$sum": "$quantity" }}},
		]
		options={}
		return pipeline, options
	
	itemcodes = _map(nth(0), over_demand)
	data_df = []
	historical_data = list(mongo_dao.apply_aggregate(*monthly_stock_moves(itemcodes, fromDate, toDate)))
	sort_fun = compose(take('item_id'), take('_id'))
	summaries={}
	for k, group in od._groupby(historical_data, sort_fun):
		dates = sorted(group, key=compose(take('timestamp'), take('_id')))
		dates.reverse()
		summaries[k]=_map(lambda x: [x['_id']['timestamp'], x['quantity']],dates)
	return summaries

def normalize_monthly_sales(months, sales_m):
	_months = months.copy()
	monthly_sales=[]
	for s in sales_m:
		_months.pop(_months.index(s[0]))
	for m in _months:
		sales_m.append([m,0])
	return sorted(sales_m, key=lambda x:x[0], reverse=True)
	
def compute_demands(item_rows, keyfunc, qty_field, items_datasource):
	over_demand = []
	origin = 'orders' if qty_field=='product_qty' else 'sales'
	for k,g in od._groupby(item_rows, keyfunc):
		items = list(g)
		item = items_datasource.by_id(k)
		itemID = item['id']
		demand = functools.reduce(lambda x,y: x+y[qty_field],items,0)
		over_demand.append([itemID, item['default_code'], item['name'], demand, origin])
	return over_demand
### FETCH TRANSFERS FROM EXTERNAL WAREHOUSES

def get_ext_wh_transfers(odoo_api, start_date):
# start_date : dt.datetime(2026,1,21)
	start_date_str = start_date.strftime("%Y-%m-%d %H:%M:%S") if isinstance(start_date, dt.datetime) else start_date
	rdt_or_lgs=[14,38]
	_domain = build_odoo_all_conditions([['state','!=','done'],['picking_type_id', 'in' ,rdt_or_lgs]
										 , ['date','>',start_date_str]])
	wh_transfers = odoo_api.extract_from_odoo('stock.picking', _domain,['name', 'date','location_id', 'location_dest_id', 'picking_type_id', 'move_line_ids'])
	aml_fields =  ['date', 'product_id','quantity', 'location_id', 'state', 'move_id', 'picking_id', 'package_id']
	transfer_moves = flatten(map(take('move_line_ids'), wh_transfers))
	transfers = odoo_api.extract_from_odoo('stock.move.line', id_in(transfer_moves),aml_fields)
	return transfers

def get_ordered_items(odoo_cache, since_date_str):
	odoo_api = odoo_cache._api
	# FETCH DATA FROM PURCHASE ORDERS
	po_fields=['date_planned', 'display_name', 'partner_id', 'order_line', 'picking_ids',
			   'receipt_status', 'state', 'partner_ref', 'picking_type_id']
	po = odoo_api.extract_from_odoo('purchase.order', ['&',['receipt_status','!=', 'full'], ['state', 'in', ['draft','sent','purchase']]]
	,po_fields)
	recent_po = od._filter_(po, [lambda x: x['date_planned'] if x['date_planned'] else '2000-01-01', od._gt(since_date_str)])
	items_in_po = flatten(_map(take('order_line'),recent_po))
	po_items = odoo_api.extract_from_odoo('purchase.order.line', id_in(items_in_po), ['name', 'order_id', 'product_qty', 'product_id'])
	po_items = merge_into(po_items, index_on_id(recent_po), 'order_id', ['date_planned', 'partner_id', 'display_name', 'state', 'picking_type_id'])
	po_items = merge_into(po_items, odoo_cache.items.to_dict(), 'product_id', ['name'], renamed=['itemname'])
	return recent_po, po_items

def compute_days_ratio(date: dt.datetime):
	ratios=[0, 0.2, 0.5, 0.7, 0.8, 1]
	days = [1, 8, 16, 22, 32]
	iratio=0
	day = date.day
	for i, (p1, p2) in enumerate(itertools.pairwise(days)):
		if p1<=day and day<p2:
			iratio = i+1
	return ratios[iratio]

def compute_demand_rows(odoo_cache, items_demand, sales, stocks, ordered, transfered):
	data=[]
	data_fields=build_fields("""itemid
itemcode
name
quantity
ratio
sales
p_order
transfer
stocks
origin""")
	s2_stock = stocks[0]
	for itemid, code, name, qty, *rest in items_demand:
		origin=rest[0]
		values=[]
		values = values + [[itemid], code, name, qty]
		s2stock = s2_stock[itemid] if itemid in s2_stock else 0
		ratio = qty / s2stock if s2stock>0 else 99
		if origin=='sales':
			ratio = (qty / (qty+s2stock)) if qty+s2stock>0 else 99
		values.append(ratio)
		values.append(sales[itemid] if itemid in sales else [])
		values.append(True if itemid in ordered else False)
		values.append(True if itemid in transfered else False)
		values = values + [_map(lambda x: x[itemid] if itemid in x else 0, stocks)]
		values.append(origin)
		data.append(values)
	
	demands = [{k:v for k,v in zip(data_fields, d)} for d in data]
	merge_into(demands, odoo_cache.items.to_dict(), 'itemid', ['seller_ids'])
	merge_into(demands, odoo_cache.suppliers.to_dict(), 'seller_ids', ['cardname', 'partner_id'])
	merge_into(demands, odoo_cache.partners.to_dict(), 'partner_id', ['category_id'])
	for d in demands:
		_sales = _map(lambda x: x[1] if len(x)>0 else 0,d['sales'])
		avg_sales=0
		if len(_sales)>1:
			avg_sales=np.average(_sales[1:])
		d['avg_sales']=avg_sales
	return sorted(demands, key=take('ratio'))

def to_2f(input):
	return f"{input:.2f}"

def compute_historical_sales(mongo_dao, items_demand):
	toDate = reset_to_midnight(dt.datetime.today())
	pastDate= toDate - relativedelta(months=3)
	fromDate = dt.datetime(pastDate.year, pastDate.month, 1)
	sales = compute_sales_summaries(mongo_dao, items_demand, fromDate, toDate)
	months=[]
	for k, v in compute_months_dict_betweenDates(fromDate, toDate).items():
		months.append([f"{k}-{str(v).zfill(2)}" for k,v in itertools.product([k],v)])
	months = flatten(months)
	for i, i_sales in sales.items():
		sales[i] = normalize_monthly_sales(months, i_sales)
	return sales