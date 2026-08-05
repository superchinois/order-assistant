# coding: utf-8
import re
import datetime as dt
import itertools
import os

import pandas as pd
import numpy as np
import datetime as dt
from compose import compose

def path_to(folder):
    outputs_folder=folder
    def _join_filename(filename):
        return os.sep.join([outputs_folder, filename])
    return _join_filename

def to_runDate(isodate):
    from zoneinfo import ZoneInfo
    inFmt = "%Y-%m-%d %H:%M:%S"
    utc_tz = "UTC"
    run_tz = 'Indian/Reunion'
    _d = dt.datetime.strptime(isodate, inFmt)
    _time = dt.datetime.combine(_d.date(), _d.time(), ZoneInfo(utc_tz))
    _time_in_run_tz = _time.astimezone(ZoneInfo(run_tz))
    return _time_in_run_tz.strftime('%Y-%m-%d %H:%M')

def get_timestamp(with_hour=True):
    date_fmt="%y%m%d"
    hour_fmt="%Hh%M"
    fmts=[date_fmt]
    if with_hour:
        fmts.append(hour_fmt)
    ts_fmt="-".join(fmts)
    return dt.datetime.now().strftime(ts_fmt)

def to_csv(dataframe,filename,sep=";",index=False, header=True, with_hour=True):
    output_path=path_to_outputs("".join([filename, "_{}".format(get_timestamp(with_hour)),".csv"]))
    dataframe.to_csv(output_path,sep=sep, index=index, header=header)
    
def add_days(odoo_date, nb_days):
    start = dt.datetime.strptime(odoo_date.split(' ')[0], "%Y-%m-%d")
    future = start + dt.timedelta(days=nb_days)
    outFmt = "%Y-%m-%d %H:%M:%S"
    return future.strftime(outFmt)
    
def _dt(isodate):
    inFmt = "%Y-%m-%d"
    outFmt = "%Y-%m-%d %H:%M:%S"
    return dt.datetime.strptime(isodate, inFmt ).strftime(outFmt)

def to_dt(isodate):
    inFmt = "%Y-%m-%d %H:%M:%S"
    return dt.datetime.strptime(isodate, inFmt )

# FUNCTIONAL METHODS
def _and(funs):
    return lambda x: all(map(lambda f: f(x), funs))
def _or(funs):
    return lambda x: any(map(lambda f: f(x), funs))
def _map(fun, iterable):
    return list(map(fun, iterable))
def _unique_map(fun, iterable):
    return list(set(map(fun, iterable)))
def _filter(fun, iterable):
    return list(filter(fun, iterable))
def flatten(iterable):
    return list(itertools.chain(*iterable))
def flat_map(fun, iterable):
    return flatten(map(fun, iterable))
def _contains(substr):
    def _isIn(x):
        return substr in x if x else False
    return _isIn
def _search(pattern):
    def _regexSearch(x):
        return re.search(pattern, x).group(1)
    return _regexSearch
def _match(pattern):
    def _regexMatch(x):
        return re.match(pattern, x)
    return _regexMatch
def multi_match(patterns):
    def _multi_match(x):
        return any(_map(lambda p: _match(p)(x), patterns))
    return _multi_match

def nth(index):
    def _take_from(x):
        return x[index]
    return _take_from
def take(field):
    def _take(x):
        if field in x:
            return x[field]
        else:
            return False
    return _take
def takes(*argv):
    def _takes(x):
        return {f: x[f] for f in argv}
    return _takes

def nths(*argv):
    def _takes(x):
        current_x=x
        for i in argv:
            current_x = current_x[i]
        return current_x
    return _takes
def _in(container):
    def _isIn(x):
        return x in container
    return _isIn
    
def _split(sep):
    def split_(value):
        return value.split(sep)
    return split_
def _lt(threshold):
    def __lt(value):
        return value < threshold
    return __lt
def _gt(threshold):
    def __gt(value):
        return value > threshold
    return __gt
def _eq(val):
    def __eq(x):
        return x==val
    return __eq
    
def _neq(val):
    def __neq(x):
        return x!=val
    return __neq
    
def _groupby(iterable, sort_function):
    return itertools.groupby(sorted(iterable, key=sort_function), key=sort_function)


take_nth_fun = lambda f: lambda x,y,z: _and([take(x), compose(f(z),nth(y), take(x))])
take_fun = lambda f: lambda x,y: _and([take(x), compose(f(y), take(x))])
take_nth_eq = take_nth_fun(_eq)
take_nth_contains = take_nth_fun(_contains)
take_eq = take_fun(_eq)
take_contains = take_fun(_contains)
take_match = take_fun(_match)


def build_fields(string_block):
    return string_block.split('\n')
        
def in_(odoo_field, searched_values):
    return [[odoo_field, "in", searched_values]]
def id_eq(value):
    return [["id","=", value]]
def id_in(values):
    return [["id","in", values]]
def eq_(field, value):
    return [[field,"=",value]]

def rename_dict_keys(dict_, renamed):
    result = dict_.copy()
    for old, new in renamed.items():
        result[new] = result.pop(old)
    return result

def group_keys_on_values(data, key_name, value_name):
    grouped = {}
    for r in data.itertuples():
        key = getattr(r, key_name)
        value = getattr(r, value_name)
        if value not in grouped:
            grouped[value]=[]
        grouped[value].append(key)
    return grouped

def get_id_or_else(elseValue):
    def _get(odooResult):
        if len(odooResult)==1:
            return odooResult[0]["id"]
        else:
            return elseValue
    return _get  

dot_split=_split('.')

def to_odoo_fields(fields):
    radicals = map(lambda x:nth(0)(x.split(".")), fields)
    result = []
    for r in radicals:
        if r not in result:
            result.append(r)
    return result

def get_values(dot_fields):
    _fields = _map(dot_split, dot_fields)
    def _get(data):
        def value_of(x):
            if len(x)>1:
                _val = data[x[0]]
                return _val[int(x[1])] if _val else False
            else:
                return data[x[0]]
        return _map(lambda x: value_of(x), _fields)
    return _get

def get_one_value(field):
    def _get(data):
        return compose(nth(0), get_values([field]))(data)
    return _get

def _filter_(data, filters_fun):
    filters_fun.reverse()
    return _filter(compose(*filters_fun), data)
    
def _filter_compose(funs, take_field, iterable):
    take_f = take(take_field)
    predicate = compose(*funs, take_f)
    return [x for x in iterable if take_f(x) and predicate(x)]

def search_multi(data, searched_field, queries):
    if not queries or not data:
        return []
        
    # 1. Combine queries into one pattern: 'ORANGINA|COCA.*50|CAPR.*POM'
    combined_pattern = "|".join(queries)
    
    # 2. Compile the pattern ONCE at the C-level
    compiled_regex = re.compile(combined_pattern)
    
    # 3. Filter using a native list comprehension
    return [
        item for item in data 
        if compiled_regex.search(str(item.get(searched_field, "")))
    ]

def insert_from(data):
    def _insert(acc, field):
        acc[field] = data[field]
        return acc
    return _insert
def index_on_id(data):
    '''data is of shape [{'id': , 'field1': , 'field2': ...etc}]
       result is of shape [{'id': {'id': ,'field1': , 'field2':}}]
    '''
    return {r['id']: {k: v for k, v in r.items()} for r in data}

def merge_into(objects, data, on_field, inserting_fields, renamed=[]):
    """
        _objects_ has a *on_field* value that is identified by an id to be matched in _data_
        the *on_field* has shape [numeric_id, some_value]
        _data_ is of shape {'id':{'field1':, field2:, ...}}
       _inserting_field_ is a field from _data_ to be inserted in _sales_
    """

    fields = list(zip(inserting_fields, inserting_fields))
    if len(inserting_fields)==len(renamed):
        fields = list(zip(inserting_fields, renamed))
    for s in objects:
        for f, out_f in fields:
            field_value = s[on_field]
            s[out_f] = False
            if field_value:
                try:
                    numeric_values = filter(lambda x: str(x).isnumeric(), field_value)
                    ids = _filter(_in(data), numeric_values)
                    s[out_f] = False
                    if len(ids)>0:
                        s[out_f] = data[ids[0]][f]
                except:
                    raise RuntimeError(f"error with {s}")
    return objects

def get_or_none(context, field):
    if field in context:
        return context[field]
    return None
def get_or_identity(context, field):
    if field in context:
        return context[field]
    return lambda x:x

def modify_rows(data, with_functions):
    '''
        data: array of dict objects
        with_functions : dict with key as fields in data element and function of form f(row) -> value
    '''
    _working_copy = data.copy()
    for row in _working_copy:
        for key, func in with_functions.items():
            row[key] = func(row)
    return _working_copy

def get_stock_pickings_after_id(odoo_api, picking_id, location_id):
    sm_domain=['&','&',
     ['id', '>', picking_id],['state', '=', 'done'],
     '|',['location_dest_id', '=', location_id],['location_id', '=', location_id]]
    stock_pickings = odoo_api.extract_from_odoo('stock.picking', sm_domain, ['partner_id','move_ids'])
    return stock_pickings
    
def get_stock_moves_from(odoo_api, location_id, start_date, end_date_excluded):
    sm_domain=['&','&','&',
     ['date_done', '>=', start_date],['date_done', '<', end_date_excluded],['state', '=', 'done'],
     '|',['location_dest_id', '=', location_id],['location_id', '=', location_id]]
    stock_pickings = odoo_api.extract_from_odoo('stock.picking', sm_domain, ['partner_id','move_ids'])
    return stock_pickings

def build_partners_mv_map(stock_moves):
    to_partners_mv_mapping = {}
    for move in stock_moves:
        partner = move['partner_id']
        if partner:
            partner_id, partner_name, *rest = partner
        else:
            partner_id = False
            partner_name = 'Client Divers'
        mv_ids = move['move_ids']
        for id in mv_ids:
            to_partners_mv_mapping[id]={'partner_name': partner_name, 'partner_id': partner_id}
    return to_partners_mv_mapping

### Inject customer name into move object

def augment_moves(all_moves,to_partners_mv_mapping, odoo_data):
    seller_ids_to_suppliers = odoo_data.suppliers.to_dict()
    
    merge_into(all_moves, odoo_data.variants.to_dict(), 'product_id', ['default_code', 'seller_ids', 'categ_id', 'name', 'onhand'])
    merge_into(all_moves, odoo_data.dao.get_colisages(), 'product_id', ['qty'], renamed=['colisage'])
    merge_into(all_moves, seller_ids_to_suppliers, 'seller_ids', ['cardname'])
    for move in all_moves:
        id_move = move['id']
        if id_move in to_partners_mv_mapping:
            move['partner_name'] = to_partners_mv_mapping[move['id']]['partner_name']
            move['partner_id'] = to_partners_mv_mapping[move['id']]['partner_id']

def to_runDate(isodate):
    from zoneinfo import ZoneInfo
    inFmt = "%Y-%m-%d %H:%M:%S"
    utc_tz = "UTC"
    run_tz = 'Indian/Reunion'
    _d = dt.datetime.strptime(isodate, inFmt)
    _time = dt.datetime.combine(_d.date(), _d.time(), ZoneInfo(utc_tz))
    _time_in_run_tz = _time.astimezone(ZoneInfo(run_tz))
    return _time_in_run_tz.strftime('%Y-%m-%d %H:%M')

def fetch_data_from_odoo(odoo_cache, query):
    odoo_api = odoo_cache._api
    from_client_location=5
    rows_change_functions = {
        'colisage': lambda r: r['colisage'] if r['colisage'] else 1,
        'quantity': lambda r: r['quantity'] if not r['location_id'][0]==from_client_location else -r['quantity'],
        'date': lambda r: dt.datetime.strptime(to_runDate(r['date']), '%Y-%m-%d %H:%M')
    }
    smf=['id',
    'date',
    'company_id.0',
    'location_dest_id.0',
    'location_id.0',
    'product_id.0',
    'picking_id.0',
    'product_uom_qty',
    'quantity',
    'move_line_ids',
    'picked']
    if 'picking_id' in query :
        last_picking = query['picking_id']
        stock_moves = get_stock_pickings_after_id(odoo_api, last_picking, from_client_location)
    elif 'start_date' in query :
        start, end = _map(get_values(['start_date', 'end_date']), query)
        stock_moves = get_stock_moves_from(from_client_location, start, end)
    _moves = stock_moves
    to_partners_mv_mapping = build_partners_mv_map(_moves)
    all_moves = odoo_api.extract_from_odoo('stock.move', id_in(flatten(_map(take('move_ids'), _moves))), to_odoo_fields(smf))
    augment_moves(all_moves, to_partners_mv_mapping, odoo_cache)
    all_moves = modify_rows(all_moves, rows_change_functions)

    raw_moves_values = _map(get_values(build_fields("""id
picking_id.0
date
product_id.0
default_code
name
quantity
partner_id
partner_name
seller_ids.0
cardname
colisage""")), _filter(lambda x: len(x['move_line_ids'])>0, all_moves))

    outfields = build_fields("""smid
docnum
docdate
item_id
itemcode
dscription
quantity
partner_id
cardname
seller_id
supplier
pcb_achat""")
    return [{k:v for k,v in zip(outfields, row)} for row in raw_moves_values]