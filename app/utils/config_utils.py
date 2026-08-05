import streamlit as st
import os
from utils import function_utils as od
from utils import mongo_utils as mu
import odoo_client
from utils.mongo_utils import CacheDao
from dotenv import dotenv_values
from collections import namedtuple


def env_config():
   """Return the application configuration.

   Values come from real environment variables first (which is how
   Docker Compose injects them via `env_file:` / `environment:`), then
   fall back to a local `.env` file for non-Docker runs.
   """
   # Local fallback: read a .env file if present (ignored when absent).
   config = dict(dotenv_values(".env"))
   # OS environment variables take priority (docker-compose provides these).
   for key, value in os.environ.items():
      if value:
         config[key] = value
   return config

def get_mcp_url():
   """Return the MCP server URL from env, falling back to the default."""
   cfg = env_config()
   return cfg.get("MCP_URL") or "http://localhost:3800/mcp"

@st.cache_resource
def init_odoo_cache():
   config_fields=["ODOO_URL" ,"ODOO_DB" ,"ODOO_USERNAME" ,"ODOO_APIKEY"]
   OdooConfig = namedtuple('OdooConfig', config_fields)
   with_config = OdooConfig(*od.get_values(config_fields)(env_config()))
   odoo_api = odoo_client.API(with_config)
   odoo_cache = odoo_client.Cache(odoo_api)
   odoo_cache.reset_cache()
   return odoo_cache

@st.cache_resource
def init_mongo_dao():
   mongo_dao = CacheDao(init_odoo_cache())
   mongo_dao.init_app(mu.build_mongo_configuration(env_config()))
   return mongo_dao
