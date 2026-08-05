import streamlit as st
import utils.function_utils as od
from utils.config_utils import init_odoo_cache, init_mongo_dao
import pandas as pd

def compute_partner_ledger(api, partnerId):
    account411 = 280
    aml_fields = ['date', 'partner_id','journal_id','ref','move_name','name','debit','credit']
    account_ml_domain=["&", "&","&", ("parent_state", "=", "posted"), ("account_id", "in", [account411]), ("partner_id", "in", [partnerId]),
                   "|", ("matching_number", "=", False), ("matching_number", "ilike", "P")]

    result_rows = api.extract_from_odoo('account.move.line', account_ml_domain, aml_fields)
    result = pd.DataFrame(od.modify_rows(result_rows, {'partner_id': lambda x: x['partner_id'][1], 'journal_id':lambda x: x['journal_id'][1]}))
    if not result.empty:
        result.loc["Total"] = result.sum(numeric_only=True)
        return result.loc[:, ['date','journal_id','move_name','debit','credit', 'ref']]
    return result


st.title("Customers")

odoo_cache = init_odoo_cache()
mongo_dao = init_mongo_dao()

customers = odoo_cache.partners.to_dict().items()
custo_map = {r[1]['name']:r for r in customers}
customer_names = od._filter(lambda x: x, od._map(od.compose(od.get_one_value('name'),od.nth(1)), customers))
with st.container(width=1024):
    options = st.multiselect(
    "Select a customer name",customer_names)

    if len(options)>0:
        st.write("Client: ", custo_map[options[0]][1]['name'])
        st.write("Cardcode selected", custo_map[options[0]][1]['ref'])
        partner_id = custo_map[options[0]][0]
        nb_weeks = 8
        st.write("odoo partner id", partner_id)
        items_by_clients = mongo_dao.getItemsBoughtByClient(partner_id, nb_weeks)
        filtered_items = items_by_clients.copy()
        if not items_by_clients.empty:
            categories = items_by_clients.categorie.unique().tolist()
            if len(categories)>1:
                selected_categs = st.multiselect(
                    'Select a category', categories)
                if len(selected_categs)>0:
                	filtered_items = items_by_clients.query(f"categorie in @selected_categs")


        if 'last4w' in items_by_clients:
        	st.dataframe(filtered_items.sort_values(by=['last4w'], ascending=False))
        else:
        	st.dataframe(filtered_items)

        st.dataframe(compute_partner_ledger(odoo_cache._api, partner_id))
