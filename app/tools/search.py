import streamlit as st
import datetime as dt
import functools
from dateutil.relativedelta import relativedelta

import utils.function_utils as od
import utils.mongo_utils as mu
from utils.config_utils import init_odoo_cache, init_mongo_dao

st.title("Search")

odoo_cache = init_odoo_cache()
mongo_dao = init_mongo_dao()

items = odoo_cache.variants.to_dict().items()
items_map = {r[1]['name']:r for r in items}
item_names = od._filter(lambda x: x, od._map(od.compose(od.get_one_value('name'),od.nth(1)), items))


tab1, tab2 = st.tabs(["🗃 By Clients", "Last Bought"])

with st.container(width=1024):
	with tab1:
		options = st.multiselect("Select an item name",item_names)
		if len(options) > 0:
			_, first_item = items_map[options[0]]
			itemid = first_item['product_variant_ids'][0]
			itemcode = first_item['default_code']
			st.write("Itemname selected", first_item['name'])
			st.write("Itemcode selected", itemid)
			st.write("Stock sis restant : ", first_item['onhand'])
			st.write('Prix ht unit', odoo_cache.items.by_id(_)['list_price'])
			today=mu.reset_to_midnight(dt.datetime.now()+dt.timedelta(days=1))
			if itemid:
				item_sales = mongo_dao.compute_sales_for_itemcode({"item_id": itemid}, today-relativedelta(months=3), today)
				st.data_editor(item_sales, column_config={
					'moy': st.column_config.NumberColumn(format="accounting"),
					'remplis.': st.column_config.NumberColumn(format="percent"),
					})
	with tab2:
		options = st.multiselect("Select an item or multiple",item_names)
		today=mu.reset_to_midnight(dt.datetime.now()+dt.timedelta(days=1))
		nb_days_before=21
		if len(options)>0:
			itemcodes = od._map(lambda x: items_map[x][1]['product_variant_ids'][0],options)
			result = mongo_dao.getSalesForItems(itemcodes, today-dt.timedelta(days=nb_days_before), today)
			if not result.empty:
				last_bought_df = result.sort_values(by=['docdate'], ascending=False).reset_index().loc[:, ['docdate','dscription','quantity','cardname']]
				df_event = st.dataframe(last_bought_df, key='data_bought', on_select='rerun', selection_mode=['multi-cell'])
				selected_cells = df_event.selection['cells']
				quantity_cells = od._filter(lambda x: x[1]=='quantity', selected_cells)
				if len(quantity_cells) > 1:
					st.write('Somme: ',functools.reduce(lambda x, y: x+last_bought_df.at[y[0], y[1]],quantity_cells, 0))