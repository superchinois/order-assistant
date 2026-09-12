import unittest
import pandas as pd


class TestWarehousesLogic(unittest.TestCase):
    def setUp(self):
        self.data = pd.DataFrame([
            {
                "tmpl_id": 1, "item_id": 101, "supplier": "CIPA", "dscription": "Prod 1",
                "s2": 10.0, "s1": 0.0, "lgs": 5.0, "rdt": 0.0, "bad": 0.0, "ext_wh": 5.0,
                "day_cover": 1.5, "7d": 6.67, "prev7d": 5.0, "14d": 6.0, "prev14d": 5.5,
                "proj7d": 7, "proj14d": 14, "daily_sales_last_6d": "[1, 2, 0, 1, 1, 2]"
            },
            {
                "tmpl_id": 2, "item_id": 102, "supplier": "FRANSA", "dscription": "Prod 2",
                "s2": 20.0, "s1": 5.0, "lgs": 0.0, "rdt": 10.0, "bad": 5.0, "ext_wh": 15.0,
                "day_cover": 4.0, "7d": 5.0, "prev7d": 4.0, "14d": 4.5, "prev14d": 4.0,
                "proj7d": 5, "proj14d": 10, "daily_sales_last_6d": "[1, 1, 1, 1, 0, 1]"
            },
            {
                "tmpl_id": 3, "item_id": 103, "supplier": "HAPI FRANCE", "dscription": "Prod 3",
                "s2": 50.0, "s1": 10.0, "lgs": 0.0, "rdt": 0.0, "bad": 20.0, "ext_wh": 20.0,
                "day_cover": 8.0, "7d": 6.25, "prev7d": 6.0, "14d": 6.0, "prev14d": 6.0,
                "proj7d": 7, "proj14d": 14, "daily_sales_last_6d": "[1, 1, 1, 1, 1, 1]"
            },
        ])

    def test_multi_supplier_selection(self):
        selected_suppliers = ["CIPA", "FRANSA"]
        filtered = self.data.query("supplier in @selected_suppliers").sort_values(
            by=["supplier", "day_cover"]
        )
        self.assertEqual(len(filtered), 2)
        self.assertListEqual(filtered["supplier"].tolist(), ["CIPA", "FRANSA"])

    def test_single_supplier_selection(self):
        selected_suppliers = ["HAPI FRANCE"]
        filtered = self.data.query("supplier in @selected_suppliers")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["supplier"], "HAPI FRANCE")

    def test_warehouse_columns_present(self):
        expected_cols = ["s2", "s1", "lgs", "rdt", "bad", "ext_wh"]
        for col in expected_cols:
            self.assertIn(col, self.data.columns)

    def test_highlight_low_cover(self):
        cutoff = 5

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
                    elif cover < cutoff:
                        styles[i] = 'color: orange; font-weight: bold'
            return styles

        # Row 0: day_cover = 1.5 (< 2)
        r0 = self.data.iloc[0]
        s0 = dict(zip(r0.index, highlight_low_cover(r0)))
        self.assertEqual(s0['dscription'], 'color: red; font-weight: bold')
        self.assertEqual(s0['day_cover'], 'color: red; font-weight: bold')

        # Row 1: day_cover = 4.0 (< cutoff 5, >= 2)
        r1 = self.data.iloc[1]
        s1 = dict(zip(r1.index, highlight_low_cover(r1)))
        self.assertEqual(s1['dscription'], '')
        self.assertEqual(s1['day_cover'], 'color: orange; font-weight: bold')

        # Row 2: day_cover = 8.0 (>= cutoff 5)
        r2 = self.data.iloc[2]
        s2 = dict(zip(r2.index, highlight_low_cover(r2)))
        self.assertEqual(s2['dscription'], '')
        self.assertEqual(s2['day_cover'], '')


if __name__ == "__main__":
    unittest.main()
