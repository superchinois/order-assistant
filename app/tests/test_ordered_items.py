import unittest

from data_connectors import sales_service
from data_connectors.sales_service import get_ordered_items
from utils import forecast_utils


def make_po(po_id, picking_type_id, date_planned='2026-02-01 00:00:00', line_id=None):
    return {
        'id': po_id,
        'date_planned': date_planned,
        'display_name': f'P{po_id:05d}',
        'partner_id': [5, 'SUPPLIER'],
        'order_line': [line_id if line_id is not None else po_id * 10],
        'picking_ids': [],
        'receipt_status': 'partial',
        'state': 'purchase',
        'partner_ref': f'REF{po_id}',
        'picking_type_id': picking_type_id,
    }


class FakeOdooApi:
    """Returns fixtures as-is; fixtures must already satisfy the server-side domain."""

    def __init__(self, purchase_orders, purchase_order_lines):
        self.purchase_orders = purchase_orders
        self.purchase_order_lines = purchase_order_lines
        self.queried_line_ids = []

    def extract_from_odoo(self, model, domain, fields):
        if model == 'purchase.order':
            return [dict(po) for po in self.purchase_orders]
        if model == 'purchase.order.line':
            wanted = set(domain[0][2])
            self.queried_line_ids.append(wanted)
            return [dict(line) for line in self.purchase_order_lines if line['id'] in wanted]
        raise AssertionError(f'unexpected model: {model}')


class FakeItems:
    def to_dict(self):
        return {}


class FakeOdooCache:
    def __init__(self, api):
        self._api = api
        self.items = FakeItems()


class TestOrderedItemsPickingTypeFilter(unittest.TestCase):
    def setUp(self):
        # Purchase orders as returned by Odoo for the existing domain
        # (receipt_status != full, state in draft/sent/purchase).
        self.pos = [
            make_po(1, [79, 'Transfert interne']),        # excluded picking type
            make_po(2, [9, 'Receipts']),                  # kept
            make_po(3, False),                            # unset -> kept
            make_po(4, [79, 'Transfert interne'],
                    date_planned='2025-12-01 00:00:00'),  # excluded by date too
        ]
        self.lines = [
            {'id': 10, 'name': 'Item 1', 'order_id': [1, 'P00001'],
             'product_qty': 1, 'product_id': [100, 'ITEM1']},
            {'id': 20, 'name': 'Item 2', 'order_id': [2, 'P00002'],
             'product_qty': 2, 'product_id': [200, 'ITEM2']},
            {'id': 30, 'name': 'Item 3', 'order_id': [3, 'P00003'],
             'product_qty': 3, 'product_id': [300, 'ITEM3']},
            {'id': 40, 'name': 'Item 4', 'order_id': [4, 'P00004'],
             'product_qty': 4, 'product_id': [400, 'ITEM4']},
        ]
        self.api = FakeOdooApi(self.pos, self.lines)
        self.cache = FakeOdooCache(self.api)

    def test_excludes_picking_type_79_from_purchase_orders(self):
        recent_po, _ = get_ordered_items(self.cache, '2026-01-01')
        self.assertEqual([po['id'] for po in recent_po], [2, 3])

    def test_excludes_picking_type_79_from_purchase_order_lines(self):
        _, po_items = get_ordered_items(self.cache, '2026-01-01')
        self.assertEqual(sorted(item['id'] for item in po_items), [20, 30])
        self.assertEqual(
            sorted(item['order_id'][0] for item in po_items), [2, 3]
        )

    def test_does_not_query_lines_of_excluded_purchase_orders(self):
        get_ordered_items(self.cache, '2026-01-01')
        self.assertEqual(self.api.queried_line_ids, [{20, 30}])

    def test_keeps_purchase_orders_with_unset_picking_type(self):
        recent_po, _ = get_ordered_items(self.cache, '2026-01-01')
        self.assertIn(3, [po['id'] for po in recent_po])

    def test_picking_type_id_is_propagated_to_po_items(self):
        _, po_items = get_ordered_items(self.cache, '2026-01-01')
        by_order = {item['order_id'][0]: item['picking_type_id'] for item in po_items}
        self.assertEqual(by_order[2], [9, 'Receipts'])
        self.assertFalse(by_order[3])

    def test_forecast_utils_reuses_the_single_implementation(self):
        self.assertIs(forecast_utils.get_ordered_items, get_ordered_items)

    def test_excluded_ids_are_exposed_as_a_constant(self):
        self.assertIn(79, sales_service.EXCLUDED_PICKING_TYPE_IDS)


if __name__ == '__main__':
    unittest.main()
