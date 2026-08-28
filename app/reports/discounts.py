# DISCOUNTS PAGE
import streamlit as st
from utils.config_utils import init_odoo_cache
from utils.function_utils import takes, take, _in ,_filter, _map, compose, merge_into
import utils.function_utils as od
import datetime as dt
import pandas as pd
import itertools

st.set_page_config(layout="wide")
st.title("Promos")

odoo_cache = init_odoo_cache()
odoo_api = odoo_cache._api

pricelist_f = ['item_ids', 'create_date', 'name', 'sequence', 'linked_master_pricelists', 'master_pricelist']
all_pricelists = odoo_api.extract_from_odoo('product.pricelist', [], pricelist_f)
master_pricelists = _map(takes('name', 'id'), _filter(take('master_pricelist'), all_pricelists))

def is_pricelist_rule_valid(current_date, rule):
    date_start = rule['date_start']
    date_end = rule['date_end']
    if date_start==False and date_end==False:
        return True
    else:
        if date_start==False and current_date<=date_end:
            return True
        if date_end==False and current_date>=date_start:
            return True
        if date_start != False and date_end != False:
            if current_date >= date_start and current_date <= date_end:
                return True
    return False
    
def get_promotion_items(pricelist_itemids):
    pricelist_item_f = ['product_tmpl_id', 'date_start', 'date_end', 'final_discount_price', 'price_discount', 'pricelist_id', 
                        'origin_pricelist_id', 'base_pricelist_id', 'compute_price', 'min_quantity', 'price', 'categ_id']
    return odoo_api.extract_from_odoo('product.pricelist.item', od.id_in(pricelist_itemids), pricelist_item_f)
    
def gather_rules_from(masterlist, all_pricelists):
    masterlist_id = masterlist['id']
    lc_i = _filter(compose(lambda x: masterlist_id in x, take('linked_master_pricelists')), all_pricelists)
    # include masterlist own items ?
    pricelists = [masterlist_id]+_map(take('id'), lc_i)
    item_ids = list(itertools.chain(*_map(take('item_ids'), _filter(compose(_in(pricelists), take('id')), all_pricelists))))
    rules = _filter(lambda x: x['origin_pricelist_id']==False, get_promotion_items(item_ids))
    return rules

today = dt.datetime.today().strftime("%Y-%m-%d")
def get_rule(grouper):
    _, rules = list(grouper)
    return list(rules)[0]
    
def filter_rules_for_date(current_date, rules):
    plist_items = _filter(lambda x: is_pricelist_rule_valid(current_date, x), rules)
    groupby_product_id = itertools.groupby(sorted(plist_items, key=lambda x: x['final_discount_price']), lambda x: x['product_tmpl_id'])
    return _map(get_rule , groupby_product_id)

cash_pricelist={'name': 'Cash', 'id': 1}
rules = gather_rules_from(cash_pricelist, all_pricelists)
rules_to_copy = filter_rules_for_date(today, rules)
rules_to_copy = merge_into(rules_to_copy, odoo_cache.items.to_dict(), 'product_tmpl_id', ['categ_id', 'name', 'onhand'])
od.modify_rows(rules_to_copy, {
    'categ_id': lambda x: x['categ_id'][1] if x['categ_id'] else False,
    'date_end': lambda x: str(x['date_end'])[:10] if x['date_end'] else '\u2014'
})
promos_du_jour = pd.DataFrame(rules_to_copy).loc[:, ['name', 'categ_id', 'final_discount_price', 'date_end', 'onhand']]

if not promos_du_jour.empty:
	categories = promos_du_jour.categ_id.unique().tolist()
	if len(categories)>0:
		selected_categ = st.multiselect(
		'Select a category', categories)
		if len(selected_categ) > 0:
			filtered_promos = promos_du_jour.query(f"categ_id in {selected_categ}")
		else:
			filtered_promos = promos_du_jour.sort_values(by=['categ_id', 'name'])

	st.dataframe(filtered_promos, hide_index=True)