"""Suppliers page: empty collection must render, and the buttons must sync.

plotly is a runtime-only dependency of the page and is not installed in the test
environment, so ``setUp`` stubs it in ``sys.modules`` — the same reasoning as the
Streamlit patching in ``tests/test_discounts.py``.
"""
import datetime as dt
import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

APP_DIR = Path(__file__).resolve().parents[1]  # .../app
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from utils.mongo_utils import SyncResult

PLOTLY_STUBS = {
    'plotly': mock.MagicMock(),
    'plotly.express': mock.MagicMock(),
    'plotly.graph_objects': mock.MagicMock(),
}


class FakeDao:
    def __init__(self, last=None, state=None):
        self._last = last
        self._state = state
        self.sync_calls = []

    def last_record(self):
        return self._last

    def get_sync_state(self):
        return self._state

    def apply_aggregate(self, pipeline, options):
        return iter([])

    def sync_from_odoo(self, since=None):
        self.sync_calls.append(since)
        return SyncResult('incremental', 3, dt.datetime(2026, 11, 1),
                          dt.datetime(2026, 11, 2), 0, None, dt.datetime(2026, 11, 2))


class FakePartners:
    @staticmethod
    def values():
        return []


class SuppliersPageTest(unittest.TestCase):
    def setUp(self):
        import streamlit
        import utils.config_utils as config_utils
        self.st_calls = []
        self.buttons = {}
        self.dao = FakeDao()

        def record(name):
            def _record(*args, **kwargs):
                self.st_calls.append((name, args, kwargs))
                if name == 'button' and args:
                    self.buttons[args[0]] = kwargs
                if name == 'date_input':
                    return dt.date(2026, 9, 1)
                return []
            return _record

        self._patchers = [
            mock.patch.dict(sys.modules, PLOTLY_STUBS),
            mock.patch.object(config_utils, 'init_odoo_cache',
                              lambda: SimpleNamespace(partners=FakePartners())),
            mock.patch.object(config_utils, 'init_mongo_dao', lambda: self.dao),
            mock.patch.object(streamlit, 'session_state', {}),
        ]
        for name in ['set_page_config', 'title', 'header', 'caption', 'button',
                     'multiselect', 'date_input', 'success', 'info', 'warning']:
            self._patchers.append(mock.patch.object(streamlit, name, record(name)))
        for patcher in self._patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        sys.modules.pop('reports.suppliers', None)
        self.addCleanup(sys.modules.pop, 'reports.suppliers', None)

    def _load(self):
        return importlib.import_module('reports.suppliers')

    def _calls(self, name):
        return [(args, kwargs) for cmd, args, kwargs in self.st_calls if cmd == name]

    def test_empty_collection_renders_and_says_never(self):
        page = self._load()
        headers = self._calls('header')
        self.assertTrue(any('never' in str(args[0]) for args, _kwargs in headers))
        self.assertTrue(hasattr(page, 'update_mongo'))  # imported without raising

    def test_update_button_reports_the_last_movement_date(self):
        self.dao._last = {'docnum': 10, 'docdate': dt.datetime(2026, 11, 19),
                          'timestamp': '2026-11-19 09:00'}
        self._load()
        headers = self._calls('header')
        self.assertTrue(any('2026-11-19 09:00' in str(args[0]) for args, _kwargs in headers))

    def test_update_callback_syncs_and_the_next_rerun_renders_a_success(self):
        self._load()
        callback = self.buttons['Mettre à jour mouvements']['on_click']
        callback(*self.buttons['Mettre à jour mouvements']['args'])
        self.assertEqual(self.dao.sync_calls, [None])

        # Streamlit reruns the script after the callback: session_state keeps the
        # result and the page body renders it on that rerun.
        self.st_calls.clear()
        sys.modules.pop('reports.suppliers')
        self._load()

        successes = self._calls('success')
        self.assertTrue(any('3' in str(args[0]) for args, _kwargs in successes))

    def test_rewind_button_passes_the_chosen_date_as_since(self):
        self._load()
        callback = self.buttons['Re-synchroniser depuis cette date']['on_click']
        callback(*self.buttons['Re-synchroniser depuis cette date']['args'])

        self.assertEqual(self.dao.sync_calls, [dt.datetime(2026, 9, 1, 0, 0)])


if __name__ == '__main__':
    unittest.main()
