from utils import mongo_utils as mu
from utils import function_utils as od
from utils.function_utils import _map, compose, nth, take, _filter, _and, _in, build_fields
from abc import ABC, abstractmethod

import datetime as dt
import pandas as pd
import numpy as np
import functools


def get_local_suppliers(odoo_cache):
    local_categ=138
    local_suppliers = (
        partner['name']
        for partner in odoo_cache.partners.values()
        if od.take_fun(od._contains)('category_id', local_categ)(partner)
    )
    return list(local_suppliers)

class ProjectionStrategy(ABC):
    def compute(self, trends_df, masterdata):
        trends_df = trends_df.merge(masterdata.loc[:,['itemid', 'categorie', 'supplier', 'pcb_achat']]
                            , left_on='tmpl_id', right_on='itemid', how='inner')
        trends_df.loc[:,'proj7d']  = np.ceil(7*trends_df['7d']/trends_df['pcb_achat'])
        trends_df.loc[:,'proj14d'] = np.ceil(14*trends_df['14d']/trends_df['pcb_achat'])
        return trends_df

class LocalSuppliersProjection(ProjectionStrategy):

    def __init__(self, odoo_cache):
        self.odoo_cache = odoo_cache
        self.purchase_create_date =  mu.reset_to_midnight(dt.datetime.now()) + dt.timedelta(days=-7)
        local_suppliers = get_local_suppliers(odoo_cache)
        self._local_suppliers = local_suppliers


    def compute(self, trends_df, masterdata):
        local_ordered = get_ordered_local_itemids(self.odoo_cache, self.purchase_create_date, self._local_suppliers)
        included_suppliers = self._local_suppliers
        local_filter = "day_cover<10 and supplier in @included_suppliers and item_id not in @local_ordered"
        return super().compute(trends_df, masterdata).query(local_filter)

class WarehouseItemsProjection(ProjectionStrategy):
    def compute(self, trends_df, masterdata):
        surg_frais_suppliers = od.build_fields("""FRANSA
CIPA
PARIS STORE DISTRIB.
LABEYRIE FINE FOOD
HAPI FRANCE
SENGELE MARTIN SASU
XIONG HAI GALASIE""")
        categs = ['FRAIS', 'SURGELES']
        cold_filter = "day_cover<10 and supplier in @surg_frais_suppliers and categorie in @categs"
        return super().compute(trends_df, masterdata).query(cold_filter).sort_values(by='day_cover')

class SalesService:
    def __init__(self, odoo_cache, mongo_dao):
        self.odoo_cache = odoo_cache
        self.odoo_api = odoo_cache._api
        self.mongo_inv_dao = mongo_dao

    def _init_mongo_dao(self, odoo_cache, settings):
        mongo_dao = mu.CacheDao(odoo_cache)
        mongo_dao.init_app(mu.build_mongo_configuration(settings.as_dict()))
        return mongo_dao

    def get_sales_and_trends(self):
        """
        Compile sales between the current days and 10 weekds before.
        Compute average sales over 7 past days and 7 days prior to that. Same thing for 14 past days 
        Trends computation is for all items
        """
        today     = mu.reset_to_midnight(dt.datetime.now())#+dt.timedelta(days=1))
        sinceDate = mu.getStartDateOfPeriod(today, 10) # 10 weeks

        one_w_earlier = today + dt.timedelta(days=-7)
        prev_one_w    = one_w_earlier + dt.timedelta(days=-7)
        prev_two_w    = prev_one_w + dt.timedelta(days=-14)

        to_iso_fmt = lambda d: d.strftime("%Y-%m-%d")
        isotoday         = to_iso_fmt(today)
        isoone_w_earlier = to_iso_fmt(one_w_earlier)
        isoprev_one_w    = to_iso_fmt(prev_one_w)
        isoprev_two_w    = to_iso_fmt(prev_two_w)

        # FETCH SALE DATA FROM `sinceDate` TO `today`
        result = self.mongo_inv_dao.find_query(sales_for_items_between_dates(sinceDate, today))
        excluded_items=[5938]
        sold_past_week = set(convert_to_tmpl_id(self.odoo_cache, result.query("item_id not in @excluded_items and docdate < @isotoday and docdate > @isoone_w_earlier").item_id.values))

        last_week_sold_items = _map(compose(nth(0), take('product_variant_ids')),
                            _filter(_and([take('id'), compose(_in(sold_past_week), take('id'))])
                                    ,self.odoo_cache.variants.values()))

        raw_historical_data = pd.DataFrame(self.mongo_inv_dao.apply_aggregate(*stock_moves_for_itemcodes(last_week_sold_items, sinceDate, today)))
        pivotted = pivot_(raw_historical_data.query("timestamp<@isotoday and timestamp>@isoprev_two_w"))
        frequent_items = pd.DataFrame(pivotted.to_dict(orient='records'))
        trends = compute_metrics(frequent_items)
        return trends

    def compute_projections(self, trends_df, masterdata, strategy):
        return strategy.compute(trends_df, masterdata)


def sales_for_items_between_dates(fromDate, toDate):
    query={"$and":[{"docdate":{"$gte":fromDate}}, {"docdate":{"$lte": toDate}}]}
    return query

def convert_to_tmpl_id(odoo_cache, variant_ids):
    return _map(compose(take('id'), odoo_cache.variants.by_id), variant_ids)

def stock_moves_for_itemcodes(itemcodes, from_date: dt.datetime, to_date: dt.datetime):
    projected_f = ["_id", "item_id","partner_id", "itemcode", "dscription", "quantity", "docnum"]
    pipeline = [
        {"$match":{"$and": [{"item_id":{"$in": itemcodes}}, {"docdate":{"$gte":from_date}}, {"docdate":{"$lte":to_date}}]}},
        {"$project": {k:v for k,v in zip(projected_f, [0]+[1]*(len(projected_f)-1))}|
         {"timestamp":{"$dateToString": {"format":"%Y-%m-%d", "date":"$docdate"}}}},
    ]
    options={}
    return pipeline, options

def set_convert_date(date_format, input_format="%Y-%m-%d"):
    def _from_string(date_string):
        date = dt.datetime.strptime(date_string, input_format)
        return date.strftime(date_format)
    return _from_string
    
def pivot_(dataframe):
    if dataframe.empty :
        return pd.DataFrame()
    else:
        index_fields=["item_id","itemcode", "dscription"]
        start_date_pos = len(index_fields)
        values_fields=["quantity"]
        columns_fields=["timestamp"]
        pvdf = pd.pivot_table(dataframe, index=index_fields,values=values_fields, columns=columns_fields,aggfunc=['sum'], fill_value=0)
        pivotted = pd.DataFrame(pvdf.to_records())
        pivotted = od.normalize_itemcode(pivotted)
        display_date_format = set_convert_date("%a %m-%d")
        renamed_array = _map(lambda x: {x:eval(x)[-1]},pivotted.columns.tolist()[start_date_pos:])
        reordered_dates = _map(lambda x: list(x.values()), renamed_array)
        renamed = functools.reduce(lambda x, y: x|y, renamed_array, {})
        pivotted = pivotted.rename(columns={k:display_date_format(v) for k,v in renamed.items()})
        displayed_dates = _map(display_date_format, sorted(od.flatten(reordered_dates), reverse=True))
        return pivotted.loc[:, pivotted.columns.tolist()[:start_date_pos]+displayed_dates].copy()

def get_ordered_local_itemids(odoo_cache, create_date, included_suppliers):
    # PURCHASES ORDERS
    recent_pos, po_items = get_ordered_items(odoo_cache, create_date.strftime("%Y-%m-%d"))

    local_ordered    = set(_map(compose(nth(0), take('product_id'))
    ,_filter(od._and([take('id'), take('product_id'),od.take_nth_fun(_in)('partner_id',1,included_suppliers)])
    , po_items)))
    return local_ordered

def get_ordered_items(odoo_cache, since_date_str):
    odoo_api = odoo_cache._api
    # FETCH DATA FROM PURCHASE ORDERS
    po_fields=['date_planned', 'display_name', 'partner_id', 'order_line', 'picking_ids',
               'receipt_status', 'state', 'partner_ref', 'picking_type_id']
    po = odoo_api.extract_from_odoo('purchase.order', ['&',['receipt_status','!=', 'full'], ['state', 'in', ['draft','sent','purchase']]],po_fields)
    recent_po = od._filter_(po, [lambda x: x['date_planned'] if x['date_planned'] else '2000-01-01', od._gt(since_date_str)])
    items_in_po = od.flatten(_map(take('order_line'),recent_po))
    po_items = odoo_api.extract_from_odoo('purchase.order.line', od.id_in(items_in_po), ['name', 'order_id', 'product_qty', 'product_id'])
    po_items = od.merge_into(po_items, od.index_on_id(recent_po), 'order_id', ['date_planned', 'partner_id', 'display_name', 'state', 'picking_type_id', 'partner_ref'])
    po_items = od.merge_into(po_items, odoo_cache.items.to_dict(), 'product_id', ['name'], renamed=['itemname'])
    return recent_po, po_items

def compute_metrics(dataframe):
    """number in brackets are column positions. it s a list of days with the most recent at index 3
       At the moment, there are 5 days in a seven_day window ...
    """
    seven_day = [[3,8], "7d"]
    prev_7d = [[8,13], "prev7d"]
    fourteen_day = [[3,13], "14d"]
    prev_14d = [[13,23], "prev14d"]
    window = prev_14d
    metrics=[]

    for window in [seven_day, prev_7d, fourteen_day, prev_14d]:
        wind = window[0]
        name = window[1]
        metrics.append(pd.DataFrame(dataframe.iloc[:,wind[0]:wind[1]].mean(axis=1), columns=[name]))
    metrics.append(pd.DataFrame(_map(lambda x: f"{x}", dataframe.iloc[:, 3:9].values[:,::-1].tolist()), columns=['daily_sales_last_6d']))
    return od.normalize_itemcode(pd.concat([dataframe[['item_id', 'itemcode', 'dscription']], *metrics], axis=1))

