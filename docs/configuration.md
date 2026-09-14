# Configuration & Operations

## Environment variables

All configuration comes from environment variables. Docker Compose injects the whole
`.env` file into the container (`env_file: .env`); `config_utils.env_config()` also
falls back to a local `.env` file for non-Docker runs. Copy the template first:

```bash
cp .env.example .env   # then fill in real values — .env is gitignored
```

### MongoDB

| Variable | Description | Example |
|---|---|---|
| `MONGO_USER` | MongoDB user | `analytics` |
| `MONGO_PASSWORD` | MongoDB password | `••••••` |
| `MONGO_HOST` | MongoDB host (port **27017** is fixed in the URI builder) | `mongo` |
| `MONGO_DATABASE` | Database name | `analytics` |
| `MONGO_STOCK_COLLECTION` | Collection holding sales/stock-move records | `raw-data` |
| `MONGO_REVENUES_COLLECTION` | Reserved for revenue data — **not used yet** | `rev-raw-data` |

The connection URI is assembled as
`mongodb://<user>:<password>@<host>:27017` in `utils/mongo_utils.build_mongo_configuration`.

The `raw-data` collection documents need at minimum: `docnum`, `docdate`, `smid`
(sorting id), `item_id`, `itemcode`, `dscription`, `quantity`, `partner_id`,
`supplier`. Records are appended from Odoo stock pickings by the *Mettre à jour
mouvements* button on the Suppliers page.

### Odoo

| Variable | Description |
|---|---|
| `ODOO_URL` | Base URL of the Odoo instance (also used to build record deep-links) |
| `ODOO_DB` | Database name |
| `ODOO_USERNAME` | Login used for XML-RPC |
| `ODOO_APIKEY` | API key / password |

The Odoo connectivity comes from the external package
[`odoo_client`](https://github.com/superchinois/odoo_client) (pinned via
`requirements.txt` / `requirements.lock`), which provides the `API` and `Cache`
classes. `Cache` pre-loads products, variants, partners and suppliers in memory.

### Ollama (LLM)

| Variable | Description |
|---|---|
| `OLLAMA_HOST` | Ollama endpoint, e.g. `https://ollama.com` or a local instance |
| `OLLAMA_API_KEY` | Bearer token sent as `Authorization: Bearer …` |

The model is hard-coded in `app/tools/history.py` (`DEFAULT_MODEL = "glm-5.3-flash:cloud"`)
— change it there if needed.

### MCP knowledge base

| Variable | Description |
|---|---|
| `MCP_URL` | MCP server endpoint (default `http://localhost:3800/mcp`) |

Used only by the *Détails livraison* button on the Order Assistant page. The client
(`utils/mcp_client.py`) speaks JSON-RPC 2.0 over Streamable HTTP and calls the
`memory_query` tool; it is stateless (fresh `initialize` handshake per call).

### App

| Variable | Description |
|---|---|
| `PORT` | Host port mapped to the container's `8501` in docker-compose |

## Running with Docker

```bash
# 1. external network (only once)
docker network create my-net

# 2. build the image
docker build -t streamlit:latest .

# 3. run (reads .env)
docker-compose up -d

# 4. open
http://localhost:${PORT:-8501}
```

Stop with `docker-compose down`. The compose service is named `mystreamlit` and joins
the external `my-net` network (so it can reach MongoDB / MCP on the same network).
A health check probes `http://localhost:8501/_stcore/health`.

The image is built from `python:3.12-slim`; dependencies come from
`requirements.lock` (pinned, including `odoo_client` from GitHub at a fixed commit).
`requirements.txt` is the loose top-level list.

## Running tests

The `app/tests/` folder contains unit tests (currently `test_discounts.py`, which
exercises the Promos page with a fake Odoo cache — no network):

```bash
cd app
python -m unittest tests.test_discounts
```

## Timezone

Displayed run timestamps use the `Indian/Reunion` timezone
(`tools/history.py`, `tools/warehouses.py`); Mongo date grouping uses UTC dates.

## Security notes

- `.env` carries credentials and is **gitignored** — only `.env.example` is tracked.
- `app/.env.dev` is a local development convenience file; keep it out of production.
- `bank_partner_mapping.csv` ships with the app image and is read at runtime from the
  working directory (`app/`).