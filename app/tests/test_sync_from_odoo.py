"""The sync walks validation-date slices and records progress in a watermark.

No cursor is derived from movement ids: a backorder picking validated late has
a low picking id, and an id cursor can never see it again.
"""
import datetime as dt
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

APP_DIR = Path(__file__).resolve().parents[1]  # .../app
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from utils.mongo_utils import CacheDao, getStartDateOfPeriod

NOW = dt.datetime(2026, 11, 20)


class FakeStateCollection:
    def __init__(self, doc=None):
        self.doc = doc

    def find_one(self, query):
        return self.doc

    def update_one(self, query, update, upsert=False):
        watermark = update['$max']['watermark']
        current = self.doc['watermark'] if self.doc else None
        self.doc = {'_id': query['_id'],
                    'watermark': max(current, watermark) if current else watermark,
                    'updated_at': update['$set']['updated_at']}
        return SimpleNamespace()


class FakeDao(CacheDao):
    """In-memory movement store plus a fake sync-state document."""

    def __init__(self, state=None, fail_on_write=0):
        self.docs = {}
        self.queries = []
        self.config = {'MONGO_COLLECTION': 'raw-data'}
        self._state = FakeStateCollection(state)
        self._fail_on_write = fail_on_write
        self._writes = 0

    def get_state_collection(self):
        return self._state

    def importFromData(self, data_to_import):
        self._writes += 1
        if self._fail_on_write and self._writes == self._fail_on_write:
            raise RuntimeError('mongo write failed')
        documents = list(data_to_import)
        for doc in documents:
            self.docs[doc['smid']] = doc
        return len(documents)


def recording_fetch(rows_per_query):
    """returns (fetch, queries); rows_per_query(query) -> list[doc]"""
    queries = []

    def fetch(query):
        queries.append(query)
        return list(rows_per_query(query))

    return fetch, queries


def watermark_doc(watermark):
    return {'_id': 'raw-data', 'watermark': watermark, 'updated_at': watermark}


class SyncFromOdooTest(unittest.TestCase):
    def test_bootstrap_starts_at_the_pivot_anchor(self):
        dao = FakeDao()
        fetch, queries = recording_fetch(lambda q: [])
        result = dao.sync_from_odoo(fetch=fetch, now=NOW)

        self.assertEqual(result.mode, 'no_new')
        self.assertEqual(queries[0]['start_date'], getStartDateOfPeriod(NOW, 10))
        self.assertEqual(queries[0]['end_date'], min(NOW, getStartDateOfPeriod(NOW, 10) + dt.timedelta(days=14)))

    def test_incremental_starts_at_watermark_minus_overlap(self):
        dao = FakeDao(watermark_doc(dt.datetime(2026, 11, 10)))
        fetch, queries = recording_fetch(lambda q: [])
        dao.sync_from_odoo(fetch=fetch, now=NOW)

        self.assertEqual(queries[0]['start_date'], dt.datetime(2026, 11, 9, 18, 0))

    def test_the_query_never_carries_a_picking_cursor(self):
        dao = FakeDao()
        fetch, queries = recording_fetch(lambda q: [])
        dao.sync_from_odoo(fetch=fetch, now=NOW, since=dt.datetime(2026, 11, 1))

        for query in queries:
            self.assertEqual(set(query), {'start_date', 'end_date'})

    def test_backorder_validated_late_is_imported(self):
        # Wednesday's sync left this watermark; the backorder picking 705 was
        # created on Wednesday but only validated on Friday.
        dao = FakeDao(watermark_doc(dt.datetime(2026, 11, 18)))
        backorder = {'smid': 9100, 'docnum': 705, 'quantity': 4.0}
        fetch, _queries = recording_fetch(
            lambda q: [backorder] if q['start_date'] <= dt.datetime(2026, 11, 20) else [])

        dao.sync_from_odoo(fetch=fetch, now=NOW)

        self.assertIn(9100, dao.docs)
        self.assertEqual(dao.get_sync_state()['watermark'], NOW)

    def test_empty_slices_advance_the_watermark_and_terminate(self):
        start = dt.datetime(2026, 10, 1)
        dao = FakeDao()
        fetch, queries = recording_fetch(lambda q: [])
        result = dao.sync_from_odoo(fetch=fetch, now=NOW, since=start)

        self.assertGreater(len(queries), 1)
        self.assertEqual(queries[0]['start_date'], start)
        self.assertEqual(dao.get_sync_state()['watermark'], NOW)
        self.assertEqual(result.imported, 0)

    def test_max_rows_stops_the_run_and_leaves_the_rest_for_the_next_press(self):
        start = dt.datetime(2026, 10, 1)
        dao = FakeDao()
        batch = [{'smid': i, 'docnum': 1} for i in range(400)]
        fetch, queries = recording_fetch(lambda q: batch)

        result = dao.sync_from_odoo(fetch=fetch, now=NOW, since=start, max_rows=1000)

        self.assertEqual(len(queries), 3)
        self.assertEqual(result.imported, 1200)
        self.assertGreater(result.remaining_days, 0)
        self.assertEqual(dao.get_sync_state()['watermark'],
                         start + dt.timedelta(days=42))

    def test_sub_day_remainder_after_the_row_budget_reports_one_day(self):
        since = NOW - dt.timedelta(days=14, hours=3)
        dao = FakeDao()
        fetch, queries = recording_fetch(lambda q: [{'smid': 1, 'docnum': 1}])

        result = dao.sync_from_odoo(fetch=fetch, now=NOW, since=since, max_rows=1)

        self.assertEqual(len(queries), 1)
        self.assertEqual(result.imported, 1)
        self.assertEqual(result.remaining_days, 1)

    def test_rewind_never_moves_the_watermark_backwards(self):
        watermark = dt.datetime(2026, 11, 18)
        dao = FakeDao(watermark_doc(watermark))
        fetch, queries = recording_fetch(lambda q: [])

        dao.sync_from_odoo(fetch=fetch, now=NOW, since=dt.datetime(2026, 10, 1))

        self.assertEqual(queries[0]['start_date'], dt.datetime(2026, 10, 1))
        self.assertEqual(dao.get_sync_state()['watermark'], NOW)

    def test_a_failed_write_leaves_the_watermark_before_the_failed_slice(self):
        start = dt.datetime(2026, 10, 1)
        dao = FakeDao(fail_on_write=2)
        batch = [{'smid': 1, 'docnum': 1}]
        fetch, _queries = recording_fetch(lambda q: batch)

        with self.assertRaises(RuntimeError):
            dao.sync_from_odoo(fetch=fetch, now=NOW, since=start)

        self.assertEqual(dao.get_sync_state()['watermark'],
                         start + dt.timedelta(days=14))


if __name__ == '__main__':
    unittest.main()
