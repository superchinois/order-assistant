"""Regression tests for fetch_data_from_odoo's date-window branch.

That branch is the only way to fetch pickings by validation date, so the sync
depends on it. It used to fail before reaching Odoo: the query dict was mapped
over instead of read, and get_stock_moves_from was called without odoo_api.
"""
import datetime as dt
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

APP_DIR = Path(__file__).resolve().parents[1]  # .../app
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from utils.function_utils import fetch_data_from_odoo

START = dt.datetime(2026, 11, 1)
END = dt.datetime(2026, 11, 15)


class RecordingApi:
    """Records every Odoo call; returns no records."""

    def __init__(self):
        self.calls = []

    def extract_from_odoo(self, model, domain, fields):
        self.calls.append((model, domain, fields))
        return []


def fake_cache():
    empty_map = SimpleNamespace(to_dict=lambda: {})
    return SimpleNamespace(
        _api=RecordingApi(),
        items=empty_map,
        variants=empty_map,
        suppliers=empty_map,
        dao=SimpleNamespace(get_colisages=lambda: {}),
    )


def conditions(domain):
    return [term for term in domain if isinstance(term, list)]


class DateWindowFetchTest(unittest.TestCase):
    def test_date_window_queries_pickings_by_date_done(self):
        cache = fake_cache()
        fetch_data_from_odoo(cache, {'start_date': START, 'end_date': END})

        model, domain, _fields = cache._api.calls[0]
        self.assertEqual(model, 'stock.picking')
        self.assertIn(['date_done', '>=', START], conditions(domain))
        self.assertIn(['date_done', '<', END], conditions(domain))
        self.assertIn(['state', '=', 'done'], conditions(domain))

    def test_date_window_returns_empty_list_when_odoo_has_nothing(self):
        cache = fake_cache()
        result = fetch_data_from_odoo(cache, {'start_date': START, 'end_date': END})
        self.assertEqual(result, [])

    def test_id_cursor_branch_still_queries_pickings_above_the_id(self):
        cache = fake_cache()
        fetch_data_from_odoo(cache, {'picking_id': 1234})

        model, domain, _fields = cache._api.calls[0]
        self.assertEqual(model, 'stock.picking')
        self.assertIn(['id', '>', 1234], conditions(domain))


if __name__ == '__main__':
    unittest.main()
