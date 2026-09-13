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

def extract_available_packages(squants, target_warehouses=('LGS', 'RDT'), variant_id=None):
    """
    Filter stock quants to orderable packages in specified external warehouses.
    Returns a list of dicts with package details.
    """
    packages = []
    for q in squants:
        qty = q.get('quantity', 0)
        if qty <= 0:
            continue
        pkg = q.get('package_id')
        if not pkg or not isinstance(pkg, (list, tuple)) or len(pkg) < 2:
            continue
        loc = q.get('location_id')
        loc_name = loc[1] if loc and isinstance(loc, (list, tuple)) and len(loc) > 1 else ''
        wh = next((w for w in target_warehouses if loc_name.startswith(w)), None)
        if not wh:
            continue
        prod = q.get('product_id')
        prod_id = prod[0] if prod and isinstance(prod, (list, tuple)) else None
        if variant_id is not None and prod_id != variant_id:
            continue
        prod_name = prod[1] if prod and isinstance(prod, (list, tuple)) and len(prod) > 1 else ''
        lot = q.get('lot_id')
        lot_name = lot[1] if lot and isinstance(lot, (list, tuple)) and len(lot) > 1 else ''
        uom = q.get('product_uom_id')
        uom_name = uom[1] if uom and isinstance(uom, (list, tuple)) and len(uom) > 1 else ''

        packages.append({
            'quant_id': q.get('id'),
            'warehouse': wh,
            'package_id': pkg[0],
            'package_name': pkg[1],
            'lot_name': lot_name,
            'quantity': qty,
            'uom': uom_name,
            'product_id': prod_id,
            'product_name': prod_name,
            'location_name': loc_name,
        })
    return packages


def get_stock_values(stocks, item_id):
    s2stock  = stocks['s2']
    s1stock  = stocks['s1']
    lgsstock = stocks.get('lgs', {})
    rdtstock = stocks.get('rdt', {})
    badstock = stocks.get('bad', {})
    extstock = stocks['extw']
    s2   = s2stock[item_id] if item_id in s2stock else 0
    s1   = s1stock[item_id] if item_id in s1stock else 0
    lgs  = lgsstock[item_id] if item_id in lgsstock else 0
    rdt  = rdtstock[item_id] if item_id in rdtstock else 0
    bad  = badstock[item_id] if item_id in badstock else 0
    extw = extstock[item_id] if item_id in extstock else 0
    return [s2, s1, lgs, rdt, bad, extw]



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
        lgs_stock = filter_stock_quants(self.odoo_cache ,squants, ['LGS'])
        rdt_stock = filter_stock_quants(self.odoo_cache ,squants, ['RDT'])
        bad_stock = filter_stock_quants(self.odoo_cache ,squants, ['BAD'])
        ext_stock = filter_stock_quants(self.odoo_cache ,squants, ['LGS','RDT', 'BAD'])
        stocks    = {
            's2': s2_stock,
            's1': s1_stock,
            'lgs': lgs_stock,
            'rdt': rdt_stock,
            'bad': bad_stock,
            'extw': ext_stock,
        }
        return stocks

    def get_variant(self, item_id):
        return self.odoo_cache.variants.by_id(item_id)['id']

    def build_stock_merge(self, dataframe, stocks):
        urgent_df = dataframe.merge(pd.DataFrame([[r.item_id]+get_stock_values(stocks, self.get_variant(r.item_id)) for r in dataframe.itertuples()]
                , columns=['item_id', 's2', 's1', 'lgs', 'rdt', 'bad', 'ext_wh']), on='item_id', how='inner')
        urgent_df.loc[:,'day_cover'] = (urgent_df.loc[:,'s2']/urgent_df.loc[:,'7d']).round(2)
        return urgent_df

    def augment_with_stocks(self, trends):
        trends.loc[:, 'tmpl_id'] = [self.get_variant(r.item_id) for r in trends.itertuples()]
        stocks = self.get_current_stocks()
        return self.build_stock_merge(trends, stocks)

    def get_orderable_packages(self, variant_id=None, target_warehouses=('LGS', 'RDT')):
        sq_fields = ["id", "inventory_quantity", "location_id", "lot_id", "on_hand", "package_id", "product_id", "product_reference_code",
                     "quantity", "product_uom_id", "inventory_quantity_set", "warehouse_id"]
        # Filter server-side in Odoo to avoid downloading all stock quants across the whole company
        domain = [('quantity', '>', 0), ('package_id', '!=', False)]
        if variant_id is not None:
            domain.append(('product_id', '=', variant_id))
        squants = self.odoo_api.extract_from_odoo("stock.quant", domain, sq_fields)
        return extract_available_packages(squants, target_warehouses=target_warehouses, variant_id=variant_id)






