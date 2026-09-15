import unittest
import pandas as pd
from data_connectors.inventory_service import (
    extract_available_packages,
    get_transferred_package_ids,
    get_variant_transfer_summary,
)


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


class TestPackageSelectionLogic(unittest.TestCase):
    def setUp(self):
        self.mock_quants = [
            # Valid package in LGS
            {
                "id": 1001,
                "product_id": [101, "[REF1] Product 1"],
                "package_id": [501, "PACK-001"],
                "location_id": [20, "LGS/Stock"],
                "lot_id": [301, "LOT-A"],
                "quantity": 25.0,
                "product_uom_id": [1, "kg"],
            },
            # Valid package in RDT
            {
                "id": 1002,
                "product_id": [101, "[REF1] Product 1"],
                "package_id": [502, "PACK-002"],
                "location_id": [21, "RDT/Stock"],
                "lot_id": [302, "LOT-B"],
                "quantity": 30.0,
                "product_uom_id": [1, "kg"],
            },
            # Package without package_id (not orderable as package)
            {
                "id": 1003,
                "product_id": [101, "[REF1] Product 1"],
                "package_id": False,
                "location_id": [20, "LGS/Stock"],
                "lot_id": False,
                "quantity": 10.0,
                "product_uom_id": [1, "kg"],
            },
            # Quantity <= 0
            {
                "id": 1004,
                "product_id": [101, "[REF1] Product 1"],
                "package_id": [503, "PACK-003"],
                "location_id": [20, "LGS/Stock"],
                "lot_id": False,
                "quantity": 0.0,
                "product_uom_id": [1, "kg"],
            },
            # Internal warehouse (not LGS or RDT)
            {
                "id": 1005,
                "product_id": [101, "[REF1] Product 1"],
                "package_id": [504, "PACK-004"],
                "location_id": [12, "s/s/2_Stock"],
                "lot_id": False,
                "quantity": 15.0,
                "product_uom_id": [1, "kg"],
            },
            # Valid package in LGS for different product
            {
                "id": 1006,
                "product_id": [102, "[REF2] Product 2"],
                "package_id": [505, "PACK-005"],
                "location_id": [20, "LGS/Stock"],
                "lot_id": [303, "LOT-C"],
                "quantity": 40.0,
                "product_uom_id": [1, "kg"],
            },
        ]

    def test_extract_available_packages_all(self):
        packages = extract_available_packages(self.mock_quants)
        self.assertEqual(len(packages), 3)
        pack_ids = [p["package_id"] for p in packages]
        self.assertListEqual(pack_ids, [501, 502, 505])

    def test_extract_available_packages_by_variant(self):
        packages = extract_available_packages(self.mock_quants, variant_id=101)
        self.assertEqual(len(packages), 2)
        whs = [p["warehouse"] for p in packages]
        self.assertIn("LGS", whs)
        self.assertIn("RDT", whs)

    def test_extract_available_packages_excludes_transferred_packages(self):
        # Exclude package 501 (which belongs to variant 101)
        packages = extract_available_packages(self.mock_quants, variant_id=101, excluded_package_ids={501})
        self.assertEqual(len(packages), 1)
        self.assertEqual(packages[0]["package_id"], 502)

    def test_get_transferred_package_ids(self):
        transfers = [
            {"product_id": [101, "Prod 1"], "package_id": [501, "PACK-001"], "quantity": 25.0},
            {"product_id": [102, "Prod 2"], "package_id": [505, "PACK-005"], "quantity": 40.0},
            {"product_id": [103, "Prod 3"], "package_id": False, "quantity": 10.0},
        ]
        ids = get_transferred_package_ids(transfers)
        self.assertEqual(ids, {501, 505})

    def test_get_variant_transfer_summary(self):
        transfers = [
            {"product_id": [101, "Prod 1"], "package_id": [501, "PACK-001"], "quantity": 25.0},
            {"product_id": [101, "Prod 1"], "package_id": [502, "PACK-002"], "quantity": 30.0},
            {"product_id": [102, "Prod 2"], "package_id": [505, "PACK-005"], "quantity": 40.0},
        ]
        summary = get_variant_transfer_summary(transfers, variant_id=101)
        self.assertEqual(summary["package_count"], 2)
        self.assertEqual(summary["total_quantity"], 55.0)

        summary_other = get_variant_transfer_summary(transfers, variant_id=999)
        self.assertEqual(summary_other["package_count"], 0)
        self.assertEqual(summary_other["total_quantity"], 0.0)

    def test_selected_packages_summary_sorted_by_warehouse(self):
        selected = [
            {"warehouse": "RDT", "product_name": "Prod 1", "package_name": "P-RDT-1", "lot_name": "L1", "quantity": 10.0, "uom": "kg"},
            {"warehouse": "LGS", "product_name": "Prod 2", "package_name": "P-LGS-1", "lot_name": "L2", "quantity": 20.0, "uom": "kg"},
            {"warehouse": "RDT", "product_name": "Prod 3", "package_name": "P-RDT-2", "lot_name": "L3", "quantity": 15.0, "uom": "kg"},
            {"warehouse": "LGS", "product_name": "Prod 1", "package_name": "P-LGS-2", "lot_name": "L4", "quantity": 5.0, "uom": "kg"},
        ]
        df = pd.DataFrame(selected).sort_values(by=["warehouse", "product_name", "package_name"])
        self.assertListEqual(df["warehouse"].tolist(), ["LGS", "LGS", "RDT", "RDT"])


if __name__ == "__main__":
    unittest.main()
