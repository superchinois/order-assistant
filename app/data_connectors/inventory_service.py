from utils import mongo_utils as mu
from utils import function_utils as od
from utils.function_utils import _map, compose, nth, take, _filter, _and, _in, _groupby


import functools
import datetime as dt
import pandas as pd
import numpy as np

def fetch_masterdata(odoo_cache):
    fields_mapping =[('id', 'itemid'), ('default_code', 'itemcode'),
 ('name', 'itemname'),
 ('onhand', 'onhand'),
 ('categ_id.1', 'categorie')]
    additional_fields = ['packaging_ids', 'seller_ids']
    output_fields = _map(nth(1), fields_mapping)
    extracted_fields = _map(nth(0), fields_mapping)
    raw_data = _map(od.get_values(extracted_fields+additional_fields), odoo_cache.items.to_dict().values())
    _data = [{k:v for k,v in zip(output_fields+additional_fields, row)} for row in raw_data]
    od.merge_into(_data, od.index_on_id(odoo_cache.dao.packs), 'packaging_ids', ['qty'], renamed=['pcb_achat'])
    od.merge_into(_data, odoo_cache.suppliers.to_dict() , 'seller_ids', ['cardname'], renamed=['supplier'])
    od.modify_rows(_data,{'pcb_achat': lambda r: r['pcb_achat'] if r['pcb_achat'] else 1})
    for r in _data:
        for f in additional_fields:
            r.pop(f)
    return pd.DataFrame(_data)

def odfilter(*args, **kwargs):
    filters = args[1].copy()
    return od._filter_(args[0], filters)
    
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
    
def get_stock_quantities(odoo_api):
    sq_fields=["id", "inventory_quantity", "location_id", "lot_id", "on_hand", "package_id", "product_id", "product_reference_code",
          "quantity", "product_uom_id", "inventory_quantity_set", "warehouse_id"]
    squants = odoo_api.extract_from_odoo("stock.quant", [], sq_fields)
    return squants

def get_stock_values(stocks, item_id):
    s2stock  = stocks['s2']
    s1stock  = stocks['s1']
    extstock = stocks['extw']
    s2   = s2stock[item_id] if item_id in s2stock else 0
    s1   = s1stock[item_id] if item_id in s1stock else 0
    extw = extstock[item_id] if item_id in extstock else 0
    return [s2, s1, extw]



class InventoryService:
    def __init__(self, odoo_cache):
        self.odoo_cache = odoo_cache
        self.odoo_api = odoo_cache._api

    def get_masterdata(self):
        return fetch_masterdata(self.odoo_cache)

    def get_current_stocks(self):
        squants   = get_stock_quantities(self.odoo_api)
        od.modify_rows(_filter(_and([od.take_fun(od._lt)('quantity', 0),od.take_nth_eq('warehouse_id',0,1)]), squants),{'quantity':lambda x: 0})
        s2_stock  = filter_stock_quants(self.odoo_cache ,squants, ['s/s/2_'])
        s1_stock  = filter_stock_quants(self.odoo_cache ,squants, ['s/s/1_'])
        ext_stock = filter_stock_quants(self.odoo_cache ,squants, ['LGS','RDT', 'BAD'])
        stocks    = {k:v for k,v in zip(['s2', 's1', 'extw'], [s2_stock, s1_stock, ext_stock])}
        return stocks

    def get_variant(self, item_id):
        return self.odoo_cache.variants.by_id(item_id)['id']

    def build_stock_merge(self, dataframe, stocks):
        urgent_df = dataframe.merge(pd.DataFrame([[r.item_id]+get_stock_values(stocks, self.get_variant(r.item_id)) for r in dataframe.itertuples()]
                , columns=['item_id', 's2', 's1','ext_wh']), on='item_id', how='inner')
        urgent_df.loc[:,'day_cover'] = (urgent_df.loc[:,'s2']/urgent_df.loc[:,'7d']).round(2)
        return urgent_df

    def augment_with_stocks(self, trends):
        trends.loc[:, 'tmpl_id'] = [self.get_variant(r.item_id) for r in trends.itertuples()]
        stocks = self.get_current_stocks()
        return self.build_stock_merge(trends, stocks)




