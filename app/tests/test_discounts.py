"""Tests for the Promos (discounts) report page.

The page is a Streamlit script executed top-to-bottom at import time, so the
test loads it with a fake Odoo cache (no network) and asserts on the
``promos_du_jour`` DataFrame it builds and on how it renders the table.
"""
import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock

APP_DIR = Path(__file__).resolve().parents[1]  # .../app
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

ISO_DATE = r"\d{4}-\d{2}-\d{2}"
NO_END_PLACEHOLDER = "\u2014"  # em dash shown when a rule has no end date

FAKE_ITEMS = {
    7: {
        'id': 7,
        'name': 'Item Seven',
        'categ_id': [12, 'Cat A'],
        'onhand': 42,
    },
    8: {
        'id': 8,
        'name': 'Item Eight',
        'categ_id': [12, 'Cat A'],
        'onhand': 7,
    },
}

FAKE_PRLISTS = [
    {'id': 1, 'create_date': '2025-01-01', 'name': 'Cash', 'sequence': 1,
     'linked_master_pricelists': [], 'master_pricelist': True, 'item_ids': [101]},
    {'id': 2, 'create_date': '2025-01-01', 'name': 'Cash LC', 'sequence': 2,
     'linked_master_pricelists': [1], 'master_pricelist': False, 'item_ids': [101, 102]},
]

FAKE_PRLIST_ITEMS = [
    {'id': 101, 'product_tmpl_id': [7, 'Item Seven'], 'date_start': False,
     'date_end': False, 'final_discount_price': 5.0, 'price_discount': 0.1,
     'pricelist_id': [1, 'Cash'], 'origin_pricelist_id': False,
     'base_pricelist_id': False, 'compute_price': 'discount', 'min_quantity': 1,
     'price': 5.0, 'categ_id': False},
    {'id': 102, 'product_tmpl_id': [8, 'Item Eight'], 'date_start': False,
     'date_end': '2026-12-31', 'final_discount_price': 3.0, 'price_discount': 0.2,
     'pricelist_id': [2, 'Cash LC'], 'origin_pricelist_id': False,
     'base_pricelist_id': False, 'compute_price': 'discount', 'min_quantity': 1,
     'price': 3.0, 'categ_id': False},
]


class FakeApi:
    """Stands in for odoo_client.API: returns canned records per model."""

    def extract_from_odoo(self, model, domain, fields):
        return {
            'product.pricelist': FAKE_PRLISTS,
            'product.pricelist.item': FAKE_PRLIST_ITEMS,
        }.get(model, [])


class FakeItemsMap:
    def to_dict(self):
        return FAKE_ITEMS


class FakeCache:
    def __init__(self):
        self._api = FakeApi()
        self.items = FakeItemsMap()


class DiscountsPageTest(unittest.TestCase):
    def setUp(self):
        import streamlit
        import utils.config_utils as config_utils
        # Ordered log of (command, kwargs) for every Streamlit call the page makes.
        self.st_calls = []

        def record(name):
            def _record(*args, **kwargs):
                self.st_calls.append((name, kwargs))
                return []
            return _record

        self._patchers = [
            mock.patch.object(config_utils, 'init_odoo_cache', lambda: FakeCache()),
            mock.patch.object(streamlit, 'set_page_config', record('set_page_config')),
            mock.patch.object(streamlit, 'title', record('title')),
            mock.patch.object(streamlit, 'multiselect', record('multiselect')),
            mock.patch.object(streamlit, 'dataframe', record('dataframe')),
        ]
        for patcher in self._patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        sys.modules.pop('reports.discounts', None)
        self.addCleanup(sys.modules.pop, 'reports.discounts', None)

    def _load_page(self):
        return importlib.import_module('reports.discounts')

    def _row_for(self, promos, name):
        return promos.loc[promos['name'] == name].iloc[0]

    def _calls(self, name):
        return [kwargs for cmd, kwargs in self.st_calls if cmd == name]

    def test_promos_table_has_current_stock_column(self):
        page = self._load_page()
        promos = page.promos_du_jour
        self.assertIn('onhand', promos.columns)
        self.assertEqual(self._row_for(promos, 'Item Seven')['onhand'], 42)
        self.assertEqual(self._row_for(promos, 'Item Eight')['onhand'], 7)

    def test_promos_table_keeps_existing_columns(self):
        page = self._load_page()
        promos = page.promos_du_jour
        for col in ['name', 'categ_id', 'final_discount_price', 'date_end']:
            self.assertIn(col, promos.columns)

    def test_date_end_is_iso_formatted(self):
        page = self._load_page()
        promos = page.promos_du_jour
        self.assertEqual(self._row_for(promos, 'Item Eight')['date_end'], '2026-12-31')
        self.assertEqual(self._row_for(promos, 'Item Seven')['date_end'], NO_END_PLACEHOLDER)

    def test_table_is_rendered_without_index_column(self):
        self._load_page()
        dataframe_calls = self._calls('dataframe')
        self.assertTrue(len(dataframe_calls) > 0, "st.dataframe was never called")
        for kwargs in dataframe_calls:
            self.assertIs(kwargs.get('hide_index'), True)

    def test_page_is_wide_and_set_page_config_comes_first(self):
        self._load_page()
        config_calls = self._calls('set_page_config')
        self.assertEqual(len(config_calls), 1, "set_page_config must be called exactly once")
        self.assertEqual(config_calls[0].get('layout'), 'wide')
        self.assertEqual(self.st_calls[0][0], 'set_page_config',
                         "set_page_config must be the first Streamlit command")


if __name__ == '__main__':
    unittest.main()