import streamlit as st
import io
import datetime as dt
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import utils.function_utils as od
import utils.mongo_utils as mu
from utils.config_utils import init_odoo_cache, init_mongo_dao, env_config
from services.report_builder import ReportBuilder
from data_connectors.sales_service import WarehouseItemsProjection
from data_connectors.inventory_service import (
    InventoryService,
    get_transferred_package_ids,
    get_variant_transfer_summary,
)
import utils.forecast_utils as fu

output_cols = od.build_fields("""tmpl_id
supplier
itemcode
dscription
s2
day_cover
7d
prev7d
14d
prev14d
s1
lgs
rdt
bad
ext_wh""")
output_cols_proj=output_cols+['proj7d', 'proj14d','daily_sales_last_6d']

st.set_page_config(page_title="Warehouses Assistant", layout="wide")
st.title("📦 Warehouses orders")
st.write("This page will assist to order products stored in external warehouses")

if "selected_packages" not in st.session_state:
    st.session_state["selected_packages"] = {}

cutoff=5

if st.button("Générer le rapport Excel"):
    # Invalidate cached transfers and packages on report refresh
    st.session_state.pop("ext_wh_transfers", None)
    for key in list(st.session_state.keys()):
        if key.startswith("available_pkgs_"):
            del st.session_state[key]
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
    df_event = st.dataframe(
        summary,
        key="summary_wh",
        on_select="rerun",
        selection_mode="multi-row",
    )
    rows_selection = df_event.selection["rows"]
    if len(rows_selection) > 0:
        selected_suppliers = summary.iloc[rows_selection]["supplier"].tolist()

        cutoff_choice = st.radio(
            "Couverture de stock :",
            options=["< 6 jours", "< 12 jours", "Tous les articles"],
            index=0,
            horizontal=True,
            key="cutoff_choice_wh",
        )

        if cutoff_choice == "< 6 jours":
            supplier_trends = trends.query("supplier in @selected_suppliers and day_cover < 6")
            header_suffix = "Couverture < 6 jours"
        elif cutoff_choice == "< 12 jours":
            supplier_trends = trends.query("supplier in @selected_suppliers and day_cover < 12")
            header_suffix = "Couverture < 12 jours"
        else:
            supplier_trends = trends.query("supplier in @selected_suppliers")
            header_suffix = "Tous les articles"

        supplier_trends = supplier_trends.sort_values(by=["supplier", "day_cover"])

        if len(selected_suppliers) == 1:
            st.subheader(f"Articles from {selected_suppliers[0]} ({header_suffix})")
        else:
            suppliers_list_str = ", ".join(selected_suppliers)
            st.subheader(f"Articles ({len(selected_suppliers)} fournisseurs sélectionnés : {suppliers_list_str}) ({header_suffix})")

        def highlight_low_cover(row):
            styles = [''] * len(row.index)
            cover = row.get('day_cover')
            if pd.isna(cover):
                return styles
            for i, col in enumerate(row.index):
                if col == 'dscription' and cover < 2:
                    styles[i] = 'color: red; font-weight: bold'
                elif col == 'day_cover':
                    if cover < 2:
                        styles[i] = 'color: red; font-weight: bold'
                    elif cover < cutoff:
                        styles[i] = 'color: orange; font-weight: bold'
            return styles

        df_event_trends = st.dataframe(
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
                "lgs": "{:.2f}",
                "rdt": "{:.2f}",
                "bad": "{:.2f}",
                "ext_wh": "{:.2f}",
                "proj7d": "{:.0f}",
                "proj14d": "{:.0f}",
            }),
            on_select="rerun",
            selection_mode="single-row",
            key="trends_wh",
        )

        trends_rows = df_event_trends.selection["rows"]
        if len(trends_rows) > 0 and trends_rows[0] is not None and trends_rows[0] < len(supplier_trends):
            selected_trend_row = trends_rows[0]
            selected_item = supplier_trends.iloc[selected_trend_row]
            variant_id = int(selected_item.item_id)
            itemname = selected_item.dscription

            odoo_cache = init_odoo_cache()
            mongo_dao = init_mongo_dao()

            # Cache daily sales data in session_state per item to avoid redundant Mongo queries on package clicks
            cache_sales_key = f"daily_sales_{variant_id}"
            if cache_sales_key not in st.session_state:
                today_date = mu.reset_to_midnight(dt.datetime.now())
                since_date = mu.getStartDateOfPeriod(today_date, 10)
                daily_data = list(mongo_dao.apply_aggregate(*mu.stock_moves_for_itemcodes([variant_id], since_date, today_date)))
                st.session_state[cache_sales_key] = (daily_data, today_date)
            else:
                daily_data, today_date = st.session_state[cache_sales_key]

            if daily_data:

                df_raw = pd.DataFrame(daily_data)
                df_raw['displayed_date'] = pd.to_datetime(df_raw['timestamp']).dt.strftime('%a %m-%d')

                # Map partner_id to customer name (same pattern as history.py)
                def get_cardname(pid):
                    if pid:
                        result = odoo_cache.partners.by_id(pid)
                        if isinstance(result, dict) and 'name' in result:
                            return result['name']
                    return 'Client Divers'
                df_raw['cardname'] = df_raw['partner_id'].apply(get_cardname)

                df_daily = df_raw.groupby('timestamp')['quantity'].sum().reset_index()
                df_daily['timestamp'] = pd.to_datetime(df_daily['timestamp'])
                df_daily = df_daily.set_index('timestamp').sort_index()

                # Reindex to fill missing days with 0
                full_range = pd.date_range(df_daily.index.min(), today_date, freq='D')
                df_daily = df_daily.reindex(full_range, fill_value=0)
                df_daily.index.name = 'timestamp'
                df_daily = df_daily.reset_index()

                df_daily['displayed_date'] = df_daily['timestamp'].dt.strftime('%a %m-%d')

                st.subheader(f"Ventes quotidiennes - {itemname}")
                fig = px.bar(df_daily, x='displayed_date', y='quantity')
                df_daily['MA5'] = df_daily['quantity'].rolling(window=5, min_periods=1).mean()
                fig.add_trace(go.Scatter(
                    x=df_daily['displayed_date'], y=df_daily['MA5'],
                    mode='lines', name='Moyenne mobile 5j',
                    line=dict(color='orange', width=2),
                ))
                event = st.plotly_chart(fig, on_select='rerun', key="chart_wh")
                if event and len(event['selection']['points']) > 0:
                    selected_category = event['selection']['points'][0]['x']
                    selected_item_rows = df_raw.query(f"displayed_date=='{selected_category}'")
                    st.dataframe(selected_item_rows.loc[:, ['cardname', 'quantity']].sort_values(by=['quantity'], ascending=False))

            # Package selection section for the selected item
            st.subheader(f"📦 Colis disponibles en entrepôts externes (LGS / RDT) - {itemname}")

            # Fetch active external warehouse transfers
            cache_transfers_key = "ext_wh_transfers"
            if cache_transfers_key not in st.session_state:
                transfers_start_date = dt.datetime(dt.date.today().year, 1, 1)
                st.session_state[cache_transfers_key] = fu.get_ext_wh_transfers(odoo_cache._api, transfers_start_date)
            active_transfers = st.session_state[cache_transfers_key]

            # In-transit transfer indicator for this variant
            transfer_summary = get_variant_transfer_summary(active_transfers, variant_id)
            pkg_cnt = transfer_summary["package_count"]
            tot_qty = transfer_summary["total_quantity"]
            if pkg_cnt > 0 and tot_qty > 0:
                st.info(f"🚚 **En cours de transfert :** {pkg_cnt} colis ({tot_qty:.2f}) actuellement en transit depuis les entrepôts externes (exclus de la liste ci-dessous).")
            elif pkg_cnt > 0:
                st.info(f"🚚 **En cours de transfert :** {pkg_cnt} colis actuellement en transit depuis les entrepôts externes (exclus de la liste ci-dessous).")
            elif tot_qty > 0:
                st.info(f"🚚 **En cours de transfert :** {tot_qty:.2f} unités actuellement en transit depuis les entrepôts externes.")

            # Exclude packages that are already subject to an active transfer
            transferred_pkg_ids = get_transferred_package_ids(active_transfers)

            # Cache packages for the selected item in session_state so toggling rows doesn't trigger Odoo RPC
            cache_pkgs_key = f"available_pkgs_{variant_id}"
            if cache_pkgs_key not in st.session_state:
                inv_service = InventoryService(odoo_cache)
                st.session_state[cache_pkgs_key] = inv_service.get_orderable_packages(
                    variant_id=variant_id, excluded_package_ids=transferred_pkg_ids
                )
            available_pkgs = st.session_state[cache_pkgs_key]

            if available_pkgs:
                df_pkgs = pd.DataFrame(available_pkgs)
                df_pkgs["Sélectionné"] = df_pkgs["quant_id"].apply(
                    lambda qid: qid in st.session_state["selected_packages"]
                )

                cols_to_show = ["Sélectionné", "warehouse", "package_name", "lot_name", "quantity", "uom", "location_name"]
                edited_pkgs = st.data_editor(
                    df_pkgs[cols_to_show].rename(columns={
                        "warehouse": "Entrepôt",
                        "package_name": "Colis",
                        "lot_name": "Lot",
                        "quantity": "Quantité",
                        "uom": "Unité",
                        "location_name": "Emplacement",
                    }),
                    disabled=["Entrepôt", "Colis", "Lot", "Quantité", "Unité", "Emplacement"],
                    key=f"editor_pkgs_{variant_id}",
                    hide_index=True,
                    use_container_width=True,
                )

                # Sync changes into st.session_state["selected_packages"]
                for idx, row in edited_pkgs.iterrows():
                    pkg_data = available_pkgs[idx]
                    qid = pkg_data["quant_id"]
                    is_selected = row["Sélectionné"]
                    if is_selected and qid not in st.session_state["selected_packages"]:
                        st.session_state["selected_packages"][qid] = pkg_data
                    elif not is_selected and qid in st.session_state["selected_packages"]:
                        del st.session_state["selected_packages"][qid]
            else:
                st.info(f"Aucun colis identifié disponible pour cet article dans LGS ou RDT.")
    else:
        st.info("Sélectionnez un ou plusieurs fournisseurs dans le tableau ci-dessus pour afficher leurs articles.")

# Display summary of selected packages at the bottom of the page
if st.session_state.get("selected_packages"):
    st.divider()
    with st.expander("🛒 Récapitulatif des colis sélectionnés pour commande", expanded=True):
        summary_packages_df = pd.DataFrame(list(st.session_state["selected_packages"].values()))
        summary_packages_df = summary_packages_df.sort_values(by=["warehouse", "product_name", "package_name"])
        display_summary_cols = ["warehouse", "product_name", "package_name", "lot_name", "quantity", "uom", "location_name"]
        available_cols = [c for c in display_summary_cols if c in summary_packages_df.columns]
        st.dataframe(
            summary_packages_df[available_cols].rename(columns={
                "warehouse": "Entrepôt",
                "product_name": "Article",
                "package_name": "Colis",
                "lot_name": "Lot",
                "quantity": "Quantité",
                "uom": "Unité",
                "location_name": "Emplacement",
            }),
            use_container_width=True,
            hide_index=True,
        )
        if st.button("Vider la sélection de colis"):
            st.session_state["selected_packages"] = {}
            st.rerun()
