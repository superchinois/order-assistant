import unittest

from data_connectors.sales_service import convert_to_tmpl_id


class FakeVariants:
    """Mimics odoo_client's ByIdObject: unknown ids return default (None)."""

    def __init__(self, mapping):
        self._mapping = mapping

    def by_id(self, id, default=None):
        return self._mapping.get(id, default)


class FakeOdooCache:
    def __init__(self, variant_to_item):
        self.variants = FakeVariants(variant_to_item)


class TestConvertToTmplId(unittest.TestCase):
    def test_skips_variant_ids_missing_from_odoo_cache(self):
        # Mongo can keep sales rows for products deleted/archived in Odoo.
        odoo_cache = FakeOdooCache({
            10: {'id': 100},
            20: {'id': 200},
        })

        result = convert_to_tmpl_id(odoo_cache, [10, 5825, 20])

        self.assertEqual(result, [100, 200])


if __name__ == "__main__":
    unittest.main()
