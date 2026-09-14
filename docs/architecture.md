# Architecture

## Overview

The **Cash & Carry Order Assistant** is a Streamlit multipage application that helps a
Cash & Carry business decide **what to reorder, from which supplier, and when**. It
combines three external systems:

| System | Role |
|---|---|
| **Odoo** (XML-RPC) | Master data: products, variants, stock quants, partners, purchase orders, sale orders, pricelists, bank-ready data. Also the target for creating purchase orders. |
| **MongoDB** (`raw-data` collection) | Historical sales / stock-movement records (`docnum`, `docdate`, `item_id`, `itemcode`, `dscription`, `quantity`, `partner_id`, `supplier`, …). Used for trend computation so heavy history is not re-fetched from Odoo. |
| **Ollama** (chat API) | LLM that turns the generated order report into a human-readable, mail-ready recommendation summary. |
| **MCP knowledge base** (`understory`, Streamable-HTTP JSON-RPC) | Stores supplier delivery knowledge (lead times, order days, MOQs, promos). Queried via the `memory_query` tool. |

## Data flow

```text
                       ┌────────────────────────────────────────────────────┐
                       │                  Streamlit app                     │
                       │                                                    │
   Odoo (XML-RPC) ────▶│  odoo_client.Cache  ── init_odoo_cache()           │
   products/stock/POs  │        │                                            │
                       │        ▼                                            │
                       │  data_connectors/                                   │
                       │   ├─ InventoryService  (masterdata, stock quants)   │
                       │   └─ SalesService      (trends + projections)       │
                       │        │                ▲                           │
   MongoDB raw-data ──▶│        ▼                │ compute_projections       │
   sales history       │  services/ReportBuilder │ (ProjectionStrategy)      │
                       │   ├─ summary DataFrame  │                           │
                       │   ├─ Excel report (.xlsx)                           │
                       │   └─ Text/CSV report ───┐                           │
                       │                         ▼                           │
   Ollama chat ───────▶│  AI recommendations (streamed markdown)             │
                       │                                                     │
   MCP memory_query ──▶│  supplier delivery details (tools/history.py)       │
                       │                                                     │
   Odoo (write) ◀──────│  create_purchase_order() → purchase.order           │
                       └────────────────────────────────────────────────────┘
```

## Entry point & navigation

`app/streamlit_app.py` builds the navigation with `st.navigation` / `st.Page`:

- **Account** — Log in / Log out (session-state toggle; currently everyone is logged in by default)
- **Reports** — Dashboard, Suppliers, Customers, Promos
- **Tools** — Search, Forecast, Order Assistant, Ext. Warehouses, Banking

Each page is a standalone script executed top-to-bottom by Streamlit on every rerun.

## Caching

| Cache | Mechanism | Lifetime |
|---|---|---|
| Odoo cache (`init_odoo_cache`) | `st.cache_resource` around `odoo_client.Cache` | Until process restart or `st.cache_resource.clear()` (the "Mettre à jour stock" button) |
| Mongo DAO (`init_mongo_dao`) | `st.cache_resource` | Same |
| Forecast page raw data | `st.session_state["_forecast_cache"]` | 5 minutes (`_CACHE_TTL = 300`) |
| MCP delivery answers | `st.session_state["mcp_delivery::<supplier>"]` | Until "Rafraîchir" |

## Core concepts

### Sales trends (`SalesService.get_sales_and_trends`)

1. Pull Mongo sales for the last **10 weeks** (aligned on Mondays — see
   `mongo_utils.getStartDateOfPeriod`).
2. Restrict to items sold during the past week (variants → template ids).
3. Aggregate daily sales per item over the window and pivot (most recent day first).
4. `compute_metrics` produces average daily sales columns:

| Column | Meaning |
|---|---|
| `7d` | Average daily sales over the **last 7 days** |
| `prev7d` | Average daily sales over the **7 days before that** |
| `14d` | Average daily sales over the **last 14 days** |
| `prev14d` | Average daily sales over the **14 days before that** |
| `daily_sales_last_6d` | Per-day quantities of the last 6 days (newest first) |

### Stock levels (`InventoryService.get_current_stocks`)

`stock.quant` records are grouped per product variant by location prefix:

| Bucket | Odoo locations | Column |
|---|---|---|
| Main sales stock | `s/s/2_*` | `s2` |
| Secondary stock | `s/s/1_*` | `s1` |
| External warehouses | `LGS`, `RDT`, `BAD` | `ext_wh` |

Negative quants (unprocessed moves) are clamped to `0`.

### Day cover & projections

- `day_cover = s2 / 7d` → estimated **days of stock remaining** at the current sales rate.
- Projections are expressed in **purchase boxes (PCB)**: `pcb_achat` is the number of
  units per purchase packaging (defaults to 1 when unset).
  - `proj7d  = ceil(7  × 7d  / pcb_achat)` — boxes needed for the next 7 days
  - `proj14d = ceil(14 × 14d / pcb_achat)` — boxes needed for the next 14 days

### Projection strategies (`data_connectors/sales_service.py`)

| Strategy | Used by | Filter |
|---|---|---|
| `LocalSuppliersProjection` | Order Assistant | local suppliers (partner category **138**), `day_cover < 10`, item **not already on an open PO** created in the last 7 days |
| `WarehouseItemsProjection` | Ext. Warehouses | cold/frozen suppliers (FRANSA, CIPA, PARIS STORE DISTRIB., LABEYRIE FINE FOOD, HAPI FRANCE, SENGELE MARTIN SASU, XIONG HAI GALASIE), categories `FRAIS`/`SURGELES`, `day_cover < 10`, sorted by `day_cover` |

Both merge the master data (`categorie`, `supplier`, `pcb_achat`) onto the trends
before filtering.

### Report generation (`services/report_builder.py`)

`ReportBuilder.compute_report_data(strategy, cutoff=2)`:

1. trends → stock augmentation → strategy projection.
2. Builds a **summary** pivot: number of items with `day_cover ≤ 10` per supplier
   (column `under_2day_cover`), sorted descending.
3. Outputs:
   - **Excel**: one sheet per *urgent* supplier (≥ 3 items under the cutoff) + an
     `OTHERS` sheet for the rest, with conditional formatting (red when `day_cover < 3`),
     frozen panes, autofilter.
   - **Text/CSV**: the same content as markdown-ish CSV — this is what is fed to the
     LLM prompt on the Order Assistant page.

## Hard-coded Odoo identifiers

Business configuration is currently hard-coded in the code. If your Odoo database
differs, these values need adjusting:

| Value | Meaning | Where |
|---|---|---|
| `138` | Partner category = **local supplier** | `sales_service.get_local_suppliers`, forecast |
| `135` | Partner category = **import** supplier | dashboard, forecast |
| `187` | Partner category = supplier (PO creation lookup) | `tools/history.py` |
| `166`, `109` | Customer categories for future orders (devis) | `forecast_utils.get_future_orders` |
| `280` | Account id of receivables (`411`) | `reports/customers.compute_partner_ledger` |
| `1` | "Cash" master pricelist id | `reports/discounts.py` |
| Picking type `9`, location `5` | POS movements | `forecast_utils.get_pos_items` |
| Picking types `14`/`38` | Transfers involving external warehouses (RDT/LGS) | `forecast_utils.get_ext_wh_transfers` |
| Location prefixes `LGS`, `RDT`, `BAD` | External warehouses | `inventory_service`, `forecast_utils` |
| Excluded item `5938` | Item ignored in "sold last week" detection | `sales_service` |

## Functional helpers (`utils/function_utils.py`)

The codebase uses a small functional toolkit (partially from the `compose` PyPI
package): `_map`, `_filter`, `_filter_`, `take`, `nth`, `take_nth_eq`, `compose`,
`_and`/`_or`, `_in`, `_contains`, `_groupby`, `merge_into`, `index_on_id`, `id_in`,
`build_fields`, `flatten`, `normalize_itemcode`, … Odoo-style predicates include
`_eq`, `_neq`, `_gt`, `_lt`. Filters are applied as `[getter, op, value]` triples via
`odfilter` / `chain_filter`.