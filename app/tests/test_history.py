import unittest
import pandas as pd


class TestHistoryLogic(unittest.TestCase):
    def setUp(self):
        self.data = pd.DataFrame([
            {"tmpl_id": 1, "supplier": "SUPPLIER_A", "dscription": "Prod 1", "day_cover": 1.5, "proj7d": 10, "pcb_achat": 1},
            {"tmpl_id": 2, "supplier": "SUPPLIER_A", "dscription": "Prod 2", "day_cover": 4.0, "proj7d": 5, "pcb_achat": 1},
            {"tmpl_id": 3, "supplier": "SUPPLIER_A", "dscription": "Prod 3", "day_cover": 8.0, "proj7d": 15, "pcb_achat": 1},
            {"tmpl_id": 4, "supplier": "SUPPLIER_A", "dscription": "Prod 4", "day_cover": 15.0, "proj7d": 20, "pcb_achat": 1},
            {"tmpl_id": 5, "supplier": "SUPPLIER_B", "dscription": "Prod 5", "day_cover": 2.0, "proj7d": 8, "pcb_achat": 1},
        ])

    def test_filter_under_6(self):
        supplier_name = "SUPPLIER_A"
        filtered = self.data.query("supplier == @supplier_name and day_cover < 6")
        self.assertEqual(len(filtered), 2)
        self.assertListEqual(filtered["tmpl_id"].tolist(), [1, 2])

    def test_filter_under_12(self):
        supplier_name = "SUPPLIER_A"
        filtered = self.data.query("supplier == @supplier_name and day_cover < 12")
        self.assertEqual(len(filtered), 3)
        self.assertListEqual(filtered["tmpl_id"].tolist(), [1, 2, 3])

    def test_filter_all_items(self):
        supplier_name = "SUPPLIER_A"
        filtered = self.data.query("supplier == @supplier_name")
        self.assertEqual(len(filtered), 4)
        self.assertListEqual(filtered["tmpl_id"].tolist(), [1, 2, 3, 4])

    def test_highlight_low_cover(self):
        def highlight_low_cover(row):
            styles = [''] * len(row.index)
            cover = row.get('day_cover')
            if pd.isna(cover):
                return styles
            for i, col in enumerate(row.index):
                if col == 'dscription' and cover < 2:
                    styles[i] = 'color: red; font-weight: bold'
                elif col == 'day_cover':
                    if cover < 2:
                        styles[i] = 'color: red; font-weight: bold'
                    elif cover < 6:
                        styles[i] = 'color: orange; font-weight: bold'
            return styles

        # Row 1: day_cover = 1.5 (< 2)
        r1 = self.data.iloc[0]
        s1 = dict(zip(r1.index, highlight_low_cover(r1)))
        self.assertEqual(s1['dscription'], 'color: red; font-weight: bold')
        self.assertEqual(s1['day_cover'], 'color: red; font-weight: bold')

        # Row 2: day_cover = 4.0 (< 6, >= 2)
        r2 = self.data.iloc[1]
        s2 = dict(zip(r2.index, highlight_low_cover(r2)))
        self.assertEqual(s2['dscription'], '')
        self.assertEqual(s2['day_cover'], 'color: orange; font-weight: bold')

        # Row 3: day_cover = 8.0 (>= 6)
        r3 = self.data.iloc[2]
        s3 = dict(zip(r3.index, highlight_low_cover(r3)))
        self.assertEqual(s3['dscription'], '')
        self.assertEqual(s3['day_cover'], '')

    def test_purchase_order_only_critical_items(self):
        supplier_name = "SUPPLIER_A"
        # Even if all items are displayed
        supplier_trends = self.data.query("supplier == @supplier_name")
        lines_to_order = []
        for row in supplier_trends.itertuples():
            if pd.notna(row.day_cover) and row.day_cover < 6:
                item_id = row.tmpl_id
                pack_qty = row.pcb_achat
                qty = max(0, row.proj7d)
                if qty > 0:
                    lines_to_order.append((item_id, qty, pack_qty))

        self.assertEqual(len(lines_to_order), 2)
        self.assertEqual(lines_to_order[0], (1, 10, 1))
        self.assertEqual(lines_to_order[1], (2, 5, 1))


if __name__ == "__main__":
    unittest.main()
