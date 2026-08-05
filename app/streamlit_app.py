import streamlit as st


if "logged_in" not in st.session_state:
    st.session_state.logged_in = True

def login():
    if st.button("Log in"):
        st.session_state.logged_in = True
        st.rerun()

def logout():
    if st.button("Log out"):
        st.session_state.logged_in = False
        st.rerun()

login_page = st.Page(login, title="Log in", icon=":material/login:")
logout_page = st.Page(logout, title="Log out", icon=":material/logout:")

dashboard = st.Page(
    "reports/dashboard.py", title="Dashboard", icon=":material/dashboard:", default=True
)
suppliers = st.Page("reports/suppliers.py", title="Suppliers", icon=":material/bug_report:")
customers = st.Page(
    "reports/customers.py", title="Customers", icon=":material/notification_important:"
)
discounts = st.Page("reports/discounts.py", title="Promos", icon=":material/percent_discount:")
search = st.Page("tools/search.py", title="Search", icon=":material/search:")
forecast = st.Page("tools/forecast.py", title="Forecast", icon=":material/monitoring:")
history = st.Page("tools/history.py", title="Order Assistant", icon=":material/analytics:")
banking = st.Page("tools/banking.py", title="Banking", icon=":material/account_balance:")
warehouses = st.Page("tools/warehouses.py", title="Ext. Warehouses", icon=":material/package_2:")
if st.session_state.logged_in:
    pg = st.navigation(
        {
            "Account": [logout_page],
            "Reports": [dashboard, suppliers, customers, discounts],
            "Tools": [search, forecast, history, warehouses, banking],
        }
    )
else:
    pg = st.navigation([login_page])

pg.run()
