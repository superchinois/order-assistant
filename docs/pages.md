# Pages — User Guide

The app navigation has three groups: **Reports**, **Tools**, and **Account**.
Screens are bilingual (FR/EN); this guide summarizes what each page shows and how to
use it.

---

## Reports

### Dashboard

A **calendar of incoming local purchase orders** (streamlit-calendar, month-list view).
Purchase orders since `2026-01-01` that are not fully received are split into:

- *Import* POs (supplier has category **135**) — not shown on the calendar,
- *Local* POs — one event per order, colored:
  - 🔴 red — arrival date already passed (late),
  - 🟢 green — expected today,
  - 🟣 violet — future.

Clicking an event shows a link button **"Ouvrir … dans Odoo"** that opens the purchase
order record (`ODOO_URL/odoo/purchase/<id>`).

### Suppliers ("Sorties Article Par Fournisseurs")

Per-supplier item movement analysis over the last **10 weeks**.

1. **Update buttons**
   - *Mettre à jour mouvements* — imports into MongoDB all stock moves newer than the
     last stored document (`docnum`).
   - *Mettre à jour stock* — clears the Streamlit caches so Odoo master data/stock is
     re-fetched.
2. Select one or more **suppliers** (auto-completed from suppliers with recent sales,
   i.e. partner category **187**).
3. Choose a **category** if the supplier sells several.
4. A pivot table shows daily quantities per item over the last 10 weeks plus:
   - `dcover` — days of cover = `onhand / average daily quantity` (items under 2 days
     of cover are highlighted in red),
   - the table is sorted by `dcover` ascending.
5. **Multi-cell selection**: select several daily-quantity cells to get a quick
   calculation panel — sum, previous-period sum, number of days, average per day,
   resulting cover, and the **trend percentage** versus the previous period.
6. Selecting a row draws the **daily bar chart with a 5-day moving average**; clicking
   a bar lists the **customers** behind that day's quantity.

### Customers

Customer-facing purchasing history and receivables.

1. Select a **customer**.
2. Items bought in the last **8 weeks**: weekly pivot (`itemcode`, `dscription`, per-week
   totals, `occurences`, `total`, `moy`, `last4w`, `categorie`, `onhand`), filterable by
   category, sorted by `last4w`.
3. The **partner ledger**: receivable lines (account 411) that are not fully
   reconciled (`matching_number = False` or like `P…`) with debit/credit and a total row.

### Promos

Today's promotional prices.

- Reads the **Cash master pricelist** (id 1) and all linked pricelists, keeps rules
  valid **today** (`date_start`/`date_end` window), one rule per product
  (lowest `final_discount_price`).
- Table: item, category, discounted price, end date (`—` when open-ended), on-hand.
- Filter by category.

---

## Tools

### Search

Two tabs, both driven by an item multiselect:

- **🗃 By Clients** — sales of the selected item per customer over the last
  **3 months** (monthly columns, `total`, `freq`, `moy`, and `remplis.` — how the last
  month compares to the historical average, formatted as a percentage). A ` TOTAL
  CLIENTS` row summarizes the market.
- **Last Bought** — individual sale records of the selected items over the last
  **21 days** (`docdate`, description, quantity, customer), newest first. Multi-cell
  selection of quantity cells shows their sum.

### Forecast

Helps detect **under-stocked items** before placing orders. Two radio choices:

- *Source of lines* — **Ventes passées** (recent POS/store sales from the last 14 days)
  or **Devis en cours** (open quotation lines from the last 10 days, customer categories
  166/109).
- *Fournisseurs* — **Local** or **Import** (partner category 135 tag).

For each demand row the page computes:

- current stock in the three buckets (`s2`, `s1`, `ext_wh`),
- `ratio` — demand versus stock (99 when stock is 0),
- monthly sales history (last 3 months),
- whether the item is already **ordered** (open PO) or **transfered** (in transit from
  an external warehouse),
- `proj_sales` — remaining expected sales today, based on the month-to-date progress
  (`compute_days_ratio`).

Items already on a PO are hidden; the **under-stocked list** (ratio > 0.7, empty stock,
or stock below projected sales) is grouped by supplier in expanders, showing stock,
projected sales, average sales, origin, quantity, ratio, monthly sales, and — for
quotations — the underlying customer orders.

### Order Assistant (main workflow)

The end-to-end replenishment page:

1. **Générer le rapport Excel** — runs trends + stocks + `LocalSuppliersProjection`,
   builds the Excel report and a text version; stores everything in session state
   (timestamp shown in `Indian/Reunion` time).
2. **🤖 Générer recommandations IA** — sends the text report to the Ollama chat model
   (default `glm-5.3-flash:cloud`) which classifies items by supplier and urgency
   (*critical / urgent not critical / to monitor*) as mail-ready markdown.
3. **Download** the `.xlsx` (`rapport_stocks.xlsx`).
4. Select a **supplier row** → items of that supplier with `day_cover < 6`
   (low cover in red), each item showing `proj7d`/`proj14d` in boxes.
5. Select an **item row** → daily sales chart (bar + 5-day moving average) over the
   last 10 weeks; clicking a bar lists the customers of that day.
6. **Créer commande d'achat pour \<supplier\>** — creates a real Odoo purchase order:
   - lines for every item with `proj7d > 0`, quantities in **boxes** (`pcb_achat`),
   - expected date = tomorrow 04:00,
   - success message with a direct link to the PO in Odoo.
7. **📦 Détails livraison — \<supplier\>** — asks the MCP knowledge base
   (`memory_query`) for lead time, order days, MOQ, promotions, unavailable items and
   pending orders; the answer is cached until *Rafraîchir*.

### Ext. Warehouses

Same reporting flow as the Order Assistant but for products stored in **external
warehouses**, using `WarehouseItemsProjection` (cold/frozen suppliers, categories
`FRAIS`/`SURGELES`). Produces `rapport_stocks_surg.xlsx` and a per-supplier drill-down
table. This page is report-only — it does not create purchase orders.

### Banking (Import Banking)

Converts a bank statement **Excel export** into Odoo bank-statement-ready rows.

1. Upload the statement file (parsed from row 17 onward; a trailing `TOTAL` row is read
   for verification).
2. The parser groups the statement blocks, extracts date, reference, debit/credit,
   label, and `Info Compl` notes.
3. **Partner matching** through `bank_partner_mapping.csv` (`bank_partner;choice`,
   `;`-separated) maps the statement's debtor/beneficiary name to an Odoo partner.
4. The resulting table (`date`, `partner_id`, `amount` — negative for debits —,
   `payment_ref`, `narration`) is displayed with debit/credit sums and the file's own
   totals for cross-checking.

---

## Account

Log in / Log out toggle. `logged_in` defaults to `True` in the current build, so all
pages are reachable without credentials; the logout only hides navigation until the
next rerun.