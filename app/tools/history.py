import streamlit as st
import io
import datetime as dt
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import utils.function_utils as od
import utils.mongo_utils as mu
from utils.config_utils import init_odoo_cache, init_mongo_dao, env_config, get_mcp_url
from utils.mcp_client import memory_query, MCPClientError
from services.report_builder import ReportBuilder
from data_connectors.sales_service import LocalSuppliersProjection


import ollama


DEFAULT_MODEL = "glm-5.3-flash:cloud"
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

def build_supplier_name(odoo_cache, product, item_id):
    first_seller = odoo_cache.items.by_id(item_id)['seller_ids'][0]
    supplier_info = odoo_cache.suppliers.by_id(first_seller)
    pname, pcode = od._map(lambda x: supplier_info[x], ['product_name','product_code'])
    if pname :
        if pcode :
            return f"[{pcode}] {pname}"
        else:
            return pname
    else:
        return product['name']
        
    
def build_order_line(odoo_cache, item_id, quantity, pack_qty):
    """
    Fetch product info (via API.extract_from_odoo) and build a
    (0, 0, {...}) command tuple for purchase.order.line, the way Odoo
    expects new one2many lines.
    """
    api = odoo_cache._api
    products = api.extract_from_odoo(
        "product.product",
        [["product_tmpl_id", "=", item_id]],
        ["name", "packaging_ids", "standard_price"],
    )
    if not products:
        raise RuntimeError(f"product.product id={item_id} not found")
    product = products[0]
    supplier_name = build_supplier_name(odoo_cache, product, item_id)
    if product["packaging_ids"]:
        return (0, 0, {
            "product_id": product['id'],
            "name": supplier_name,
            "product_qty": pack_qty*quantity,
            "product_packaging_qty": quantity,
            "product_packaging_id": product["packaging_ids"][0],   # packaging COL
            "price_unit": product["standard_price"],  # adjust: e.g. use vendor price instead
        })
    else:
        return (0, 0, {
            "product_id": product['id'],
            "name": supplier_name,
            "product_qty": quantity,
            "price_unit": product["standard_price"],  # adjust: e.g. use vendor price instead
        })



def create_purchase_order(odoo_cache, partner_id, date_planned, lines):
    """
    lines: list of (item_id, quantity) tuples
    date_planned: string "YYYY-MM-DD HH:MM:SS"
    """
    order_lines = [build_order_line(odoo_cache, item_id, qty, pack_qty) for item_id, qty, pack_qty in lines]

    order_vals = {
        "partner_id": partner_id,
        "date_planned": date_planned,   # order-level expected date
        "order_line": order_lines,
    }

    return api.create_("purchase.order", [order_vals])
    
st.set_page_config(page_title="Order Assistant", layout="wide")
st.title("📦 Cash & Carry Order Assistant")

@st.cache_resource
def make_ollama_client(host: str) -> ollama.Client:
    return ollama.Client(
    host=host,
    headers={"Authorization": "Bearer " + env_config()["OLLAMA_API_KEY"]},
)


def ollama_chat_stream(client: ollama.Client, model: str, system: str, user: str):
    """Yield text chunks from Ollama as they arrive."""
    stream = client.chat(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        stream=True,
    )
    for chunk in stream:
        content = chunk["message"]["content"]
        if content:
            yield content


client = make_ollama_client(env_config()['OLLAMA_HOST'])

if st.button("Générer le rapport Excel"):
    with st.spinner("Génération du rapport..."):
        odoo_cache = init_odoo_cache()
        mongo_dao = init_mongo_dao()
        report_builder = ReportBuilder(odoo_cache, mongo_dao)
        local_strategy = LocalSuppliersProjection(odoo_cache)
        report_data = report_builder.compute_report_data(local_strategy)
        buffer = io.BytesIO()
        report_builder.output_in_excel(buffer, report_data)
        txt_data = io.StringIO()
        report_builder.output_in_text(txt_data, report_data)
        st.session_state["report_data"] = report_data
        st.session_state["report_xlsx"] = buffer.getvalue()
        st.session_state["report_text"] = txt_data.getvalue()
        st.session_state["report_generated_at"] = dt.datetime.now(ZoneInfo("Indian/Reunion"))

if "report_text" in st.session_state:
    if st.button("🤖 Générer recommandations IA"):
        system_prompt = """You are a cash and carry order assistant from SIS company. Your task is to review data from item sales and trends and make
recommendations about items to order. Classify by suppliers and by 3 level urgency (critical, urgent not critical, and to monitor).
Your response is digestible summary as markdown text that can be mailed
Sales data indications:
- column s2 is the main sale stock, s1 is a secondary stock and ext_wh is external warehouse (not SIS company)
"""
        today = dt.datetime.now().strftime("%Y-%m-%d")
        user_prompt = f"Today's date is {today}\nSales data:\n{st.session_state['report_text']}"
        with st.chat_message("assistant"):
            full_response = st.write_stream(
                ollama_chat_stream(client, DEFAULT_MODEL, system_prompt, user_prompt)
            )
            st.session_state["last_response"] = full_response

elif "last_response" in st.session_state:
    with st.chat_message("assistant"):
        st.markdown(st.session_state["last_response"])
    
if "report_xlsx" in st.session_state:
    cols = st.columns([4, 1])
    with cols[0]:
        st.download_button(
            label="Télécharger le rapport (.xlsx)",
            data=st.session_state["report_xlsx"],
            file_name="rapport_stocks.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with cols[1]:
        st.write(st.session_state["report_generated_at"].strftime("%H:%M:%S"))

if "report_data" in st.session_state:
    summary, trends = st.session_state["report_data"]
    df_event = st.dataframe(summary, key="summary", on_select="rerun")
    rows_selection = df_event.selection["rows"]
    if len(rows_selection)>0:
        selected_row = rows_selection[0]
        supplier_name = summary.iloc[selected_row,:].supplier

        cutoff_choice = st.radio(
            "Couverture de stock :",
            options=["< 6 jours", "< 12 jours", "Tous les articles"],
            index=0,
            horizontal=True,
            key="cutoff_choice",
        )

        if cutoff_choice == "< 6 jours":
            supplier_trends = trends.query("supplier == @supplier_name and day_cover < 6")
            header_suffix = "Couverture < 6 jours"
        elif cutoff_choice == "< 12 jours":
            supplier_trends = trends.query("supplier == @supplier_name and day_cover < 12")
            header_suffix = "Couverture < 12 jours"
        else:
            supplier_trends = trends.query("supplier == @supplier_name")
            header_suffix = "Tous les articles"

        st.subheader(f"Articles from {supplier_name} ({header_suffix})")

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
                    elif cover < 6:
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
                "ext_wh": "{:.2f}",
                "proj7d": "{:.0f}",
                "proj14d": "{:.0f}",
            }),
            on_select="rerun",
            key="trends",
        )

        trends_rows = df_event_trends.selection["rows"]
        if len(trends_rows) > 0 and trends_rows[0] < len(supplier_trends):
            selected_trend_row = trends_rows[0]
            selected_item = supplier_trends.iloc[selected_trend_row]
            variant_id = int(selected_item.item_id)
            itemname = selected_item.dscription

            odoo_cache = init_odoo_cache()
            mongo_dao = init_mongo_dao()
            today_date = mu.reset_to_midnight(dt.datetime.now())
            since_date = mu.getStartDateOfPeriod(today_date, 10)
            daily_data = list(mongo_dao.apply_aggregate(*mu.stock_moves_for_itemcodes([variant_id], since_date, today_date)))

            if daily_data:
                df_raw = pd.DataFrame(daily_data)
                df_raw['displayed_date'] = pd.to_datetime(df_raw['timestamp']).dt.strftime('%a %m-%d')

                # Map partner_id to customer name (same pattern as suppliers.py)
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
                event = st.plotly_chart(fig, on_select='rerun')
                if event and len(event['selection']['points']) > 0:
                    selected_category = event['selection']['points'][0]['x']
                    selected_item_rows = df_raw.query(f"displayed_date=='{selected_category}'")
                    st.dataframe(selected_item_rows.loc[:, ['cardname', 'quantity']].sort_values(by=['quantity'], ascending=False))
        
        if st.button(
            f"Créer commande d'achat pour {supplier_name}",
            help="Seuls les articles critiques (couverture < 6 jours) seront inclus dans la commande.",
        ):
            with st.spinner("Création de la commande en cours..."):
                odoo_cache = init_odoo_cache()
                api = odoo_cache._api
                
                # Fetch supplier ID
                suppliers = od._filter(od._and([od.take_fun(od._contains)('name', supplier_name),
                    od.take_fun(lambda y: lambda x: y in x)('category_id', 187)]),odoo_cache.partners.values())
                supplier_id = suppliers[0]['id'] if suppliers else None
                if supplier_id:
                    # Collect lines (critical items only: day_cover < 6)
                    lines_to_order = []
                    for row in supplier_trends.itertuples():
                        if pd.notna(row.day_cover) and row.day_cover < 6:
                            item_id = row.tmpl_id
                            pack_qty = row.pcb_achat
                            qty = max(0, row.proj7d)
                            if qty > 0:
                                lines_to_order.append((item_id, qty, pack_qty))
                    if lines_to_order:
                        try:
                            tomorrow = dt.date.today() + dt.timedelta(days=1)
                            date_planned = f"{tomorrow.strftime('%Y-%m-%d')} 04:00:00"
                            po_id = create_purchase_order(odoo_cache, supplier_id, date_planned, lines_to_order)
                            po_url = f"{env_config()['ODOO_URL']}/odoo/purchase/{po_id}"
                            st.success(f"Commande d'achat créée avec l'ID {po_id}")
                            st.markdown(f"🔗 [Voir la commande dans Odoo]({po_url})")
                        except Exception as e:
                            st.error(f"Échec de la création de la commande d'achat. Erreur: {e} \n {lines_to_order}")
                    else:
                        st.warning("Aucun article critique (couverture < 6 jours) avec une quantité à commander.")
                else:
                    st.error(f"Impossible de trouver l'ID du fournisseur pour {supplier_name}.")

        # --- Fetch delivery details for the selected supplier (MCP memory) ---
        delivery_cache_key = f"mcp_delivery::{supplier_name}"
        delivery_btn_key = f"btn_delivery::{supplier_name}"
        delivery_refresh_key = f"refresh_delivery::{supplier_name}"

        if delivery_cache_key not in st.session_state:
            if st.button(
                f"📦 Détails livraison — {supplier_name}",
                key=delivery_btn_key,
                help="Demande au serveur MCP les détails de livraison pour ce fournisseur.",
            ):
                question = (
                    f"Today is {dt.datetime.today().strftime("%a %Y-%m-%d")}"
                    f"What are the delivery details for the supplier '{supplier_name}'? "
                    "Include lead time, order days, minimum order quantity, "
                    "promotions, unavailable items and any pending orders."
                )
                with st.spinner("Interrogation de la base de connaissances…"):
                    try:
                        st.session_state[delivery_cache_key] = memory_query(
                            question, url=get_mcp_url()
                        )
                    except MCPClientError as exc:
                        st.error(
                            f"Échec de la récupération des détails de livraison : {exc}"
                        )

        if delivery_cache_key in st.session_state:
            with st.expander(
                f"Détails livraison — {supplier_name}", expanded=True
            ):
                st.markdown(st.session_state[delivery_cache_key])
                if st.button("🔄 Rafraîchir", key=delivery_refresh_key):
                    st.session_state.pop(delivery_cache_key, None)
                    st.rerun()

