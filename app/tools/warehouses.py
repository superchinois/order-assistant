import streamlit as st
import io
import datetime as dt
from zoneinfo import ZoneInfo
import pandas as pd
import utils.function_utils as od
from utils.config_utils import init_odoo_cache, init_mongo_dao, env_config
from services.report_builder import ReportBuilder
from data_connectors.sales_service import WarehouseItemsProjection

output_cols = od.build_fields("""tmpl_id
itemcode
dscription
s2
day_cover
7d
prev7d
14d
prev14d
s1
ext_wh""")
output_cols_proj=output_cols+['proj7d', 'proj14d','daily_sales_last_6d']

st.set_page_config(page_title="Warehouses Assistant", layout="wide")
st.title("📦 Warehouses orders")
st.write("This page will assist to order products stored in external warehouses")
cutoff=5
if st.button("Générer le rapport Excel"):
    with st.spinner("Génération du rapport..."):
        odoo_cache = init_odoo_cache()
        mongo_dao = init_mongo_dao()
        report_builder = ReportBuilder(odoo_cache, mongo_dao)
        strategy = WarehouseItemsProjection()
        report_data = report_builder.compute_report_data(strategy, cutoff)
        buffer = io.BytesIO()
        report_builder.output_in_excel(buffer, report_data, cutoff)
        st.session_state["report_data_"] = report_data
        st.session_state["report_xlsx_"] = buffer.getvalue()
        st.session_state["report_generated_at_"] = dt.datetime.now(ZoneInfo("Indian/Reunion"))

    
if "report_xlsx_" in st.session_state:
    cols = st.columns([4, 1])
    with cols[0]:
        st.download_button(
            label="Télécharger le rapport (.xlsx)",
            data=st.session_state["report_xlsx_"],
            file_name="rapport_stocks_surg.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with cols[1]:
        st.write(st.session_state["report_generated_at_"].strftime("%H:%M:%S"))

if "report_data_" in st.session_state:
    summary, trends = st.session_state["report_data_"]
    df_event = st.dataframe(summary, key="summary", on_select="rerun")
    rows_selection = df_event.selection["rows"]
    if len(rows_selection)>0:
        selected_row = rows_selection[0]
        supplier_name = summary.iloc[selected_row,:].supplier
        
        st.subheader(f"Articles from {supplier_name}")
        supplier_trends = trends.query("supplier== @supplier_name")
        
        def highlight_low_cover(row):
            return ['color: red; font-weight: bold' if col == 'dscription' and pd.notna(row.get('day_cover')) and row.get('day_cover') < cutoff else '' for col in row.index]
            
        st.dataframe(
            supplier_trends.loc[:, output_cols_proj]
            .style.apply(highlight_low_cover, axis=1)
            .format({
                "s2": "{:.2f}",
                "day_cover": "{:.2f}",
                "7d": "{:.2f}",
                "prev7d": "{:.2f}",
                "14d": "{:.2f}",
                "prev14d": "{:.2f}",
                "s1": "{:.2f}",
                "ext_wh": "{:.2f}",
                "proj7d": "{:.0f}",
                "proj14d": "{:.0f}",
            })
        )