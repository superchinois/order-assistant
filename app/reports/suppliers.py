import functools
from utils.config_utils import init_odoo_cache, init_mongo_dao
from utils.function_utils import _filter_, _map, nth, take, _in, _contains, compose, _filter
import utils.function_utils as od
from utils.mongo_utils import CacheDao
import utils.mongo_utils as mu

import plotly.express as px
import plotly.graph_objects as go
import datetime as dt
import pandas as pd
import streamlit as st



def update_mongo(mongo_dao, odoo_cache):
    docnum = mongo_dao.last_record()['docnum']
    data_to_import = od.fetch_data_from_odoo(odoo_cache,{'picking_id':docnum})
    mongo_dao.importFromData(data_to_import)

def set_convert_date(date_format, input_format="%Y-%m-%d"):
    def _from_string(date_string):
        date = dt.datetime.strptime(date_string, input_format)
        return date.strftime(date_format)
    return _from_string

def get_suppliers_sold(from_date: dt.datetime, to_date: dt.datetime):
    pipeline = [
        {"$match":{"$and": [{"docdate":{"$gte":from_date}}, {"docdate":{"$lt":to_date}}]}},
        {"$group": { "_id":"$supplier"}},
    ]
    options={}
    return pipeline, options

def pivot_(dataframe):
    if dataframe.empty :
        return pd.DataFrame()
    else:
        index_fields=["itemcode", "dscription", "onhand"]
        start_date_pos = len(index_fields)
        values_fields=["quantity"]
        columns_fields=["timestamp"]
        pvdf = pd.pivot_table(dataframe, index=index_fields,values=values_fields, columns=columns_fields,aggfunc=['sum'], fill_value=0)
        pivotted = pd.DataFrame(pvdf.to_records())
        display_date_format = set_convert_date("%a %m-%d")
        renamed_array = _map(lambda x: {x:eval(x)[-1]},pivotted.columns.tolist()[start_date_pos:])
        reordered_dates = _map(lambda x: list(x.values()), renamed_array)
        renamed = functools.reduce(lambda x, y: x|y, renamed_array, {})
        pivotted = pivotted.rename(columns={k:display_date_format(v) for k,v in renamed.items()})
        displayed_dates = _map(display_date_format, sorted(od.flatten(reordered_dates), reverse=True))
        return pivotted.loc[:, pivotted.columns.tolist()[:start_date_pos]+displayed_dates].copy()

def get_supplier_items(odoo_cache, fromSupplierName):
    def _items_for_seller_ids(seller_ids):
        return od._filter_(odoo_cache.items.to_dict().items(), 
                        [nth(1), take('seller_ids'), lambda x: any(_map(_in(seller_ids), x))])
    seller_ids = _map(nth(0), 
        od._filter_(odoo_cache.suppliers.to_dict().items(), [nth(1), take('cardname'), _contains(fromSupplierName)]))
    return _items_for_seller_ids(seller_ids)




def assign_cardname(partner_id):
    result = odoo_cache.partners.by_id(partner_id)
    try:
        if result and 'name' in result:
            return result['name']
        return 'Client Divers'
    except :
        raise Exception(f"Error with {partner_id} and {result}")


odoo_cache = init_odoo_cache()
mongo_dao = init_mongo_dao()
today = dt.datetime.now()+dt.timedelta(days=1)
sinceDate=mu.getStartDateOfPeriod(today, 10) # 10 weeks
display_date_format = set_convert_date("%a %m-%d")


supplier_names = _map(take('_id'), mongo_dao.apply_aggregate(*get_suppliers_sold(sinceDate, today)))
suppliers = od._filter_(odoo_cache.partners.values(),[take('category_id'), lambda x: x and 187 in x])
suppliers_map = {r['name']:r for r in suppliers}

st.set_page_config(layout="wide")
st.title('Sorties Article Par Fournisseurs')
st.header(f"Last updated: {mongo_dao.last_record()['timestamp']}")
st.button('Mettre à jour mouvements', on_click=update_mongo, args=[mongo_dao, odoo_cache])
st.button('Mettre à jour stock', on_click=st.cache_resource.clear)

with st.container(width=1024):
    options = st.multiselect(
    "Select a supplier name",sorted(od._filter(lambda x: x, supplier_names)))
    #od._map(od.take('name'), suppliers))
    if len(options)>0:
        st.write("Fournisseur: ", suppliers_map[options[0]]['name'])
        st.write("Cardcode selected", suppliers_map[options[0]]['ref'])

        item_ids = _map(nth(0),get_supplier_items(odoo_cache, options[0]))
        variants_ids = _map(compose(nth(0), take('product_variant_ids')),_filter(od._and([take('id'), compose(_in(item_ids), take('id'))]),odoo_cache.variants.values()))
        mongo_data = list(mongo_dao.apply_aggregate(*mu.stock_moves_for_itemcodes(variants_ids, sinceDate, today)))
        mongo_data = od.modify_rows(mongo_data, {'variant_id': lambda x: [x['item_id']]})
        mongo_data = od.merge_into(mongo_data, odoo_cache.variants.to_dict(),'variant_id', ['onhand', 'categ_id', 'product_id'])
        mongo_data = od.modify_rows(mongo_data, {'category': lambda x: x['categ_id'][1]})
        raw_data = pd.DataFrame(mongo_data)
        raw_data['displayed_date'] = [display_date_format(r.timestamp) for r in raw_data.itertuples()]
        raw_data['cardname'] = [assign_cardname(r.partner_id) for r in raw_data.itertuples()]

        def highlight_low_cover(row):
            return ['color: red; font-weight: bold' if col == 'dscription' and pd.notna(row.get('dcover')) and row.get('dcover') < 2 else '' for col in row.index]

        if not raw_data.empty:
            categories = raw_data.category.unique().tolist()
            if len(categories)>1:
                selected_categ = st.selectbox(
                    'Select a category', categories)
                df_for_supplier = pivot_(raw_data.query(f"category=='{selected_categ}'"))
            else:
                df_for_supplier = pivot_(raw_data)

            prev_days = df_for_supplier.iloc[:,4:10].copy()
            onhand_vec = df_for_supplier.iloc[:,2]
            df_for_supplier.insert(2, 'dcover', onhand_vec/(prev_days.sum(axis=1)/len(prev_days.columns)), allow_duplicates=False)
            float_cols = df_for_supplier.columns.values.tolist()[2:]
            format_cells = {c: "{:.2f}" for c in float_cols} 
            # 1. Reset the index of the DataFrame FIRST (and copy it explicitly)
            df_sorted = df_for_supplier.sort_values(by=['dcover']).reset_index(drop=True)

            # 2. Build the Styler object directly from df_sorted
            styled_df = df_sorted.style.apply(highlight_low_cover, axis=1).format(format_cells)

            # 3. Render in Streamlit
            df_event = st.dataframe(
                styled_df,
                key='data',
                on_select='rerun',
                selection_mode=['multi-cell']
            )

            selected_cells = df_event["selection"].get("cells", [])

            if len(selected_cells) > 1:
                selected_row = selected_cells[-1][0]
                last_selected_col = selected_cells[-1][1]
                last_index = df_sorted.columns.get_loc(last_selected_col)+1
                nb_selected = len(selected_cells)
                selected_sum = functools.reduce(lambda x, y: x+df_sorted.loc[y[0], [y[1]]].values.tolist()[0]
                ,selected_cells, 0)
                selected_onhand = df_sorted.query(f"index=={selected_cells[0][0]}").onhand.tolist()[0]
                avg_day = selected_sum/nb_selected
                previous_sum = df_sorted.iloc[selected_row, range(last_index, last_index+nb_selected)].sum()
                st.write('Somme: ',selected_sum, 'Somme prec',previous_sum,'onhand', selected_onhand)
                st.write('Nb. jours: ',nb_selected)
                st.write('Moyenne jour: ', round(avg_day, 2), 'days_cover', round(selected_onhand/avg_day,3) if avg_day>0 else 'inf')
                st.write(f"Trend over past {nb_selected} days", "{:+.2%}".format(selected_sum/previous_sum-1))              
            if len(selected_cells) > 0 :#not df_for_supplier.empty:
                # item = st.selectbox(
                #     "Select an item",
                #     df_for_supplier.dscription.tolist(),
                # )
                #one_row = df_for_supplier.query(f"dscription=='{item}'")
                one_row = df_sorted.query(f"index=={selected_cells[0][0]}")
                itemname = one_row.dscription.tolist()[0]
                st.write(itemname)
                dates      = list(one_row.columns.tolist())[4:]
                quantities = list(one_row.values[0])[4:]
                df = pd.DataFrame({'Date': dates, 'Quantity':quantities})
                fig = px.bar(df, x='Date', y='Quantity')
                # Dates are in reverse chronological order (most recent first)
                # Reverse for chronological computation, then map back for display
                df_chrono = df.iloc[::-1].reset_index(drop=True)
                df_chrono['MA5'] = df_chrono['Quantity'].rolling(window=5, min_periods=1).mean()
                df['MA5'] = df_chrono['MA5'].values[::-1].tolist()
                fig.add_trace(go.Scatter(
                    x=df['Date'], y=df['MA5'],
                    mode='lines', name='Moyenne mobile 5j',
                    line=dict(color='orange', width=2),
                ))
                
                event = st.plotly_chart(fig, on_select='rerun')
                if event and len(event['selection']['points'])>0:
                    selected_category = event['selection']['points'][0]['x']
                    st.write(f"You clicked on: {selected_category}")
                    selected_item_rows = raw_data.query(f"dscription=='{itemname.replace("'", "\\'")}' and displayed_date=='{selected_category}'")
                    st.dataframe(selected_item_rows.loc[:, ['cardname', 'quantity']].sort_values(by=['quantity'], ascending=False))