# Cash & Carry Order Assistant (Streamlit)

This project is a Streamlit-based web application designed as an **Order Assistant** for a Cash & Carry business. It connects to an Odoo backend (via XML-RPC/JSON-RPC) to fetch real-time data on products, sales, inventory stocks, and suppliers. The application then uses intelligent calculations and LLM integration (via Ollama) to analyze sales trends, calculate days of stock cover, and project ordering needs. 

The tool generates digestible overviews, creates interactive data tables to view summaries per supplier, exports to Excel, and allows users to seamlessly create Purchase Orders directly in Odoo.

## Directory Layout

```text
.
├── Dockerfile                  # Instructions to build the Streamlit environment
├── docker-compose.yml          # Docker Compose configuration to easily spin up the app
├── requirements.txt            # Python dependencies
└── app/                        # The main Streamlit application code
    ├── streamlit_app.py        # Main entrypoint for Streamlit
    ├── data_connectors/        # Handles connections to data sources
    │   ├── inventory_service.py # Fetches master data, stock levels, variants from Odoo
    │   └── sales_service.py     # Fetches sales data, calculates trends and projections
    ├── reports/                # Pages or modules rendering specific business reports
    │   ├── customers.py
    │   ├── dashboard.py
    │   ├── discounts.py
    │   └── suppliers.py
    ├── services/               # Core business logic services
    │   └── report_builder.py   # Aggregates data and formats it into Excel or Text
    ├── tools/                  # Interactive assistant tools
    │   ├── banking.py
    │   ├── forecast.py
    │   ├── history.py          # Features the Order Assistant, PO creation, and Ollama integration
    │   ├── search.py
    │   └── warehouses.py
    └── utils/                  # Shared utilities
        ├── config_utils.py     # Configuration, caching initialization, and environment vars
        ├── forecast_utils.py
        ├── function_utils.py   # General-purpose helper functions
        ├── mcp_client.py       # Thin client for the MCP knowledge-base server (memory_query)
        └── mongo_utils.py      # Optional MongoDB utilities (if configured)
```

## Running the Application with Docker Compose

The project includes a `docker-compose.yml` file to quickly run the Streamlit app. Note that the docker-compose file expects the application folder (`app`) to be mounted as a volume.

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
