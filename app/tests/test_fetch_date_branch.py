"""Regression tests for fetch_data_from_odoo's date-window branch.

That branch is the only way to fetch pickings by validation date, so the sync
depends on it. It used to fail before reaching Odoo: the query dict was mapped
over instead of read, and get_stock_moves_from was called without odoo_api.
"""
import datetime as dt
import json
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
    """Records every Odoo call; returns no records.

    The domain is round-tripped through JSON on every call, exactly like
    odoo_client's RPC (requests `json=`), so a datetime that reaches Odoo
    fails here the way it fails against the real server.
    """

    def __init__(self):
        self.calls = []

    def extract_from_odoo(self, model, domain, fields):
        json.dumps(domain)
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
        self.assertIn(['date_done', '>=', '2026-11-01 00:00:00'], conditions(domain))
        self.assertIn(['date_done', '<', '2026-11-15 00:00:00'], conditions(domain))
        self.assertIn(['state', '=', 'done'], conditions(domain))

    def test_date_window_passes_dates_as_strings_to_the_json_rpc(self):
        cache = fake_cache()
        fetch_data_from_odoo(cache, {'start_date': START, 'end_date': END})

        _model, domain, _fields = cache._api.calls[0]
        for value in ['2026-11-01 00:00:00', '2026-11-15 00:00:00']:
            self.assertIn(value, json.dumps(domain))
        self.assertNotIn('datetime', json.dumps(domain))

    def test_date_window_returns_empty_list_when_odoo_has_nothing(self):
        cache = fake_cache()
        result = fetch_data_from_odoo(cache, {'start_date': START, 'end_date': END})
        self.assertEqual(result, [])

    def test_date_window_accepts_already_formatted_dates(self):
        cache = fake_cache()
        fetch_data_from_odoo(cache, {'start_date': '2026-11-01 00:00:00',
                                     'end_date': '2026-11-15 00:00:00'})

        _model, domain, _fields = cache._api.calls[0]
        self.assertIn(['date_done', '>=', '2026-11-01 00:00:00'], conditions(domain))
        self.assertIn(['date_done', '<', '2026-11-15 00:00:00'], conditions(domain))

    def test_id_cursor_branch_still_queries_pickings_above_the_id(self):
        cache = fake_cache()
        fetch_data_from_odoo(cache, {'picking_id': 1234})

        model, domain, _fields = cache._api.calls[0]
        self.assertEqual(model, 'stock.picking')
        self.assertIn(['id', '>', 1234], conditions(domain))


if __name__ == '__main__':
    unittest.main()
