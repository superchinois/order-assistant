# Cash & Carry Order Assistant (Streamlit)

This project is a Streamlit-based web application designed as an **Order Assistant** for a Cash & Carry business. It connects to an Odoo backend (via XML-RPC/JSON-RPC) to fetch real-time data on products, sales, inventory stocks, and suppliers. The application then uses intelligent calculations and LLM integration (via Ollama) to analyze sales trends, calculate days of stock cover, and project ordering needs. 

The tool generates digestible overviews, creates interactive data tables to view summaries per supplier, exports to Excel, and allows users to seamlessly create Purchase Orders directly in Odoo.

## Documentation

Full documentation lives in [`docs/`](docs/):

- **[docs/architecture.md](docs/architecture.md)** — system overview, data flow, core
  concepts (trends, day cover, projections), caching, hard-coded Odoo identifiers.
- **[docs/pages.md](docs/pages.md)** — user guide for every page
  (Dashboard, Suppliers, Customers, Promos, Search, Forecast, Order Assistant,
  Ext. Warehouses, Banking).
- **[docs/configuration.md](docs/configuration.md)** — environment variables, Docker
  deployment, tests, and operational notes.

## Directory Layout

```text
.
├── Dockerfile                  # Instructions to build the Streamlit environment
├── docker-compose.yml          # Docker Compose configuration to easily spin up the app
├── requirements.txt            # Top-level Python dependencies (odoo_client is pulled from GitHub)
├── requirements.lock           # Pinned dependencies used by the Docker build
├── .env.example                # Template of environment variables (copy to .env)
└── app/                        # The main Streamlit application code
    ├── streamlit_app.py        # Main entrypoint for Streamlit (multipage navigation)
    ├── bank_partner_mapping.csv# Bank statement → Odoo partner mapping (Banking page)
    ├── data_connectors/        # Handles connections to data sources
    │   ├── inventory_service.py # Fetches master data, stock levels, variants from Odoo
    │   └── sales_service.py     # Fetches sales data, calculates trends and projections
    ├── reports/                # Pages or modules rendering specific business reports
    │   ├── customers.py        # Customer purchase history + partner ledger
    │   ├── dashboard.py        # Calendar of incoming local purchase orders
    │   ├── discounts.py        # Today's promotions from Odoo pricelists
    │   └── suppliers.py        # Item movements per supplier (pivot, charts, drill-down)
    ├── services/               # Core business logic services
    │   └── report_builder.py   # Aggregates data and formats it into Excel or Text
    ├── tools/                  # Interactive assistant tools
    │   ├── banking.py
    │   ├── forecast.py
    │   ├── history.py          # Features the Order Assistant, PO creation, coverage filtering, and Ollama integration
    │   ├── search.py
    │   └── warehouses.py       # Multi-supplier external warehouse orders with stock breakdown (LGS, RDT, BAD) and sales charts
    ├── tests/                  # Unit tests
    │   ├── test_discounts.py
    │   ├── test_history.py
    │   └── test_warehouses.py
    └── utils/                  # Shared utilities
        ├── config_utils.py     # Configuration, caching initialization, and environment vars
        ├── forecast_utils.py   # Demand/forecast computations for the Forecast page
        ├── function_utils.py   # Functional-style helpers (map/filter/take/compose...)
        ├── mcp_client.py       # Thin client for the MCP knowledge-base server (memory_query)
        └── mongo_utils.py      # MongoDB DAO, aggregation pipelines, date helpers
```

## Running the Application with Docker Compose

The project includes a `docker-compose.yml` file to quickly run the Streamlit app. The application code is baked into the image, and the whole `.env` file is injected into the container as OS environment variables (`env_file:`).

### Configuration
Copy the template and fill in your real credentials (the template ships with safe placeholder values):
```bash
cp .env.example .env
```

> **Security:** The `.env` file contains credentials (API keys, DB passwords) and is **gitignored** — never commit it. Only the `.env.example` template is tracked in version control.

### Prerequisites
- Docker and Docker Compose installed.
- Ensure the external network `my-net` exists, or create it:
  ```bash
  docker network create my-net
  ```
  *(Alternatively, you can edit the `docker-compose.yml` to remove the external network requirement if you don't need it).*

### Steps to Run

1. **Build the image (if necessary):**
   You can build the `streamlit:latest` image based on the provided `Dockerfile`:
   ```bash
   docker build -t streamlit:latest .
   ```

2. **Start the application:**
   Run the following command from the root of the project:
   ```bash
   docker-compose up -d
   ```

3. **Access the application:**
   Once the container is running, open your web browser and navigate to:
   ```
   http://localhost:8501
   ```

### Stopping the Application
To stop the running container, execute:
```bash
docker-compose down
```

## Running Tests

To run the unit test suite inside the Docker container:
```bash
docker exec order-assistant-mystreamlit-1 python -m unittest discover tests
```

