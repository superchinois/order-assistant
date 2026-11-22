"""Tests for CacheDao.importFromData: idempotent upserts, empty-safe."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

APP_DIR = Path(__file__).resolve().parents[1]  # .../app
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from pymongo import ReplaceOne

from utils.mongo_utils import CacheDao

DOCS = [
    {'smid': 1, 'docnum': 10, 'quantity': 2.0},
    {'smid': 2, 'docnum': 10, 'quantity': 3.0},
]


class FakeCollection:
    """Keyed on smid, so a second identical import cannot grow the store."""

    def __init__(self, fail_create_index=False):
        self.docs = {}
        self.bulk_calls = []
        self.indexes = []
        self.fail_create_index = fail_create_index

    def bulk_write(self, operations, ordered=True):
        ops = list(operations)
        self.bulk_calls.append(ops)
        for op in ops:
            self.docs[op._filter['smid']] = op._doc
        return SimpleNamespace(upserted_count=len(ops), modified_count=0)

    def create_index(self, field, **_kwargs):
        if self.fail_create_index:
            raise RuntimeError('index creation refused')
        self.indexes.append(field)


class FakeDao(CacheDao):
    def __init__(self, collection):
        self._collection = collection

    def get_collection(self):
        return self._collection


class ImportFromDataTest(unittest.TestCase):
    def test_empty_batch_returns_zero_and_writes_nothing(self):
        collection = FakeCollection()
        self.assertEqual(FakeDao(collection).importFromData([]), 0)
        self.assertEqual(collection.bulk_calls, [])

    def test_documents_are_upserted_on_smid(self):
        collection = FakeCollection()
        written = FakeDao(collection).importFromData(DOCS)

        self.assertEqual(written, 2)
        self.assertEqual(
            collection.bulk_calls[0],
            [ReplaceOne({'smid': 1}, DOCS[0], upsert=True),
             ReplaceOne({'smid': 2}, DOCS[1], upsert=True)],
        )

    def test_importing_the_same_documents_twice_does_not_duplicate(self):
        collection = FakeCollection()
        dao = FakeDao(collection)
        dao.importFromData(DOCS)
        dao.importFromData(DOCS)
        self.assertEqual(sorted(collection.docs), [1, 2])

    def test_ensure_indexes_creates_smid_and_docdate_indexes(self):
        collection = FakeCollection()
        FakeDao(collection).ensure_indexes()
        self.assertEqual(collection.indexes, ['smid', 'docdate'])

    def test_ensure_indexes_failure_is_swallowed(self):
        collection = FakeCollection(fail_create_index=True)
        FakeDao(collection).ensure_indexes()  # must not raise


if __name__ == '__main__':
    unittest.main()
