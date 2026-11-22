# Suppliers Sync Watermark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Suppliers page's MongoDB update work from an empty, stale or current collection by syncing Odoo stock pickings on `date_done` slices tracked by a persisted watermark, idempotently.

**Architecture:** `CacheDao` owns the sync policy (`sync_from_odoo`) and the state document (`sync-state` collection) so it can be unit-tested without Streamlit; the page only renders messages and offers a rewind control. Movements are fetched by validation date (`stock.picking.date_done`), never by picking id, so a backorder validated late is picked up however old its id is; writes are `ReplaceOne` upserts on `smid`, so slices, retries and repairs never duplicate rows.

**Tech Stack:** Python 3.12, Streamlit, pymongo 4.17, `odoo_client` (XML-RPC), `unittest` (no pytest).

**Spec:** `docs/superpowers/specs/2026-11-22-suppliers-sync-watermark-design.md`

## Global Constraints

- No new dependency. `pymongo.ReplaceOne` and `bulk_write` are already available.
- Tests: run from `app/` with `python -m unittest discover tests` (28 tests green at baseline).
- `date_done` is naive UTC: use a `naive_utc_now()` helper for sync comparisons. Reunion-local time is for display only.
- Fixed values: slice span **14 days**, incremental overlap **6 hours**, at most **1000 fetched rows** per press, bootstrap anchor `getStartDateOfPeriod(now, 10)` (10 weeks).
- No resume cursor may be derived from movement ids (`smid`, `docnum`). `docnum` is display/link data only.
- Writes are upserts keyed on `smid`; an empty batch is a no-op returning `0`.
- Never move the watermark backwards.
- Page labels stay in the existing mixed style: English labels, French messages.

## Review Focus

1. **Empty `raw-data` on first load** — the page must render, say `never`, and pressing the button must bootstrap from the 10-week anchor instead of raising. (Task 3, Task 5)
2. **A slice whose window contains no pickings** (shop closed, or only non-location-5 movements) — the loop must advance the watermark and terminate, not retry the same window forever. (Task 4)
3. **A picking validated late with an id below the watermark** (split delivery / backorder) — it must be imported, which is the whole point of switching to `date_done`. (Task 4)
4. **Repeated presses and repeated repairs** — no duplicate rows, so `dcover` and `7d`/`14d` stay honest. (Task 2)
5. **`sync-state` missing while `raw-data` already holds rows** — treated as a bootstrap from the anchor, no crash, no duplicates. (Task 2, Task 4)

---

### Task 1: Make the `date_done` fetch branch usable

**Files:**
- Modify: `app/utils/function_utils.py:381-383`
- Test: `app/tests/test_fetch_date_branch.py` (create)

**Interfaces:**
- Produces: `fetch_data_from_odoo(odoo_cache, {'start_date': datetime | str, 'end_date': datetime | str}) -> list[dict]` — working; each dict has the same 12 keys as the `{'picking_id': …}` branch (`smid`, `docnum`, `docdate`, `item_id`, `itemcode`, `dscription`, `quantity`, `partner_id`, `cardname`, `seller_id`, `supplier`, `pcb_achat`). Datetimes are formatted to `'%Y-%m-%d %H:%M:%S'` for the domain by `to_odoo_datetime`.
- Consumes: `get_stock_moves_from(odoo_api, location_id, start_date, end_date_excluded)` (already correct, `function_utils.py:314`).

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_fetch_date_branch.py`:

```python
"""Regression tests for fetch_data_from_odoo's date-window branch.

That branch is the only way to fetch pickings by validation date, so the sync
depends on it. It used to fail before reaching Odoo: the query dict was mapped
over instead of read, and get_stock_moves_from was called without odoo_api.
"""
import datetime as dt
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
    """Records every Odoo call; returns no records."""

    def __init__(self):
        self.calls = []

    def extract_from_odoo(self, model, domain, fields):
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
        self.assertIn(['date_done', '>=', START], conditions(domain))
        self.assertIn(['date_done', '<', END], conditions(domain))
        self.assertIn(['state', '=', 'done'], conditions(domain))

    def test_date_window_returns_empty_list_when_odoo_has_nothing(self):
        cache = fake_cache()
        result = fetch_data_from_odoo(cache, {'start_date': START, 'end_date': END})
        self.assertEqual(result, [])

    def test_id_cursor_branch_still_queries_pickings_above_the_id(self):
        cache = fake_cache()
        fetch_data_from_odoo(cache, {'picking_id': 1234})

        model, domain, _fields = cache._api.calls[0]
        self.assertEqual(model, 'stock.picking')
        self.assertIn(['id', '>', 1234], conditions(domain))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python -m unittest tests.test_fetch_date_branch -v`
Expected: the two date-window tests FAIL with `TypeError: string indices must be integers, not 'str'`; the id-cursor test PASSES (it is the regression guard).

- [ ] **Step 3: Fix the date branch**

In `app/utils/function_utils.py`, replace the body of the `elif 'start_date' in query:` branch (lines 381-383) with:

```python
    elif 'start_date' in query :
        start, end = query['start_date'], query['end_date']
        stock_moves = get_stock_moves_from(odoo_api, from_client_location, start, end)
```

The date is passed as a `datetime` and formatted to `'%Y-%m-%d %H:%M:%S'` before it reaches the domain. `odoo_client` posts JSON (not XML-RPC), so a datetime in the domain raises `TypeError: Object of type datetime is not JSON serializable`; `utils/forecast_utils.py:104-109` already formats its own date window for this reason.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python -m unittest tests.test_fetch_date_branch -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Run the full suite**

Run: `cd app && python -m unittest discover tests`
Expected: `Ran 31 tests ... OK`.

- [ ] **Step 6: Commit**

```bash
git add app/utils/function_utils.py app/tests/test_fetch_date_branch.py
git commit -m "fix(tools): make the date-window fetch branch usable"
```

---

### Task 2: Idempotent, empty-safe import plus indexes

**Files:**
- Modify: `app/utils/mongo_utils.py` (`importFromData` at :170, `init_app` at :121-124, new `ensure_indexes`)
- Test: `app/tests/test_import_from_data.py` (create)

**Interfaces:**
- Produces:
  - `CacheDao.importFromData(data_to_import) -> int` — returns the number of submitted documents (`0` for an empty iterable, and then no write is attempted). Each document is upserted with `ReplaceOne({'smid': doc['smid']}, doc, upsert=True)`; the list is written with `bulk_write(operations, ordered=False)`.
  - `CacheDao.ensure_indexes() -> None` — best-effort `create_index` on `smid` and `docdate`; never raises.
  - `CacheDao.get_collection()` — unchanged; the tests override it.
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_import_from_data.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python -m unittest tests.test_import_from_data -v`
Expected: FAIL — `AttributeError: 'FakeCollection' object has no attribute 'insert_many'` for the non-empty tests, and `AttributeError: ... 'ensure_indexes'` for the index tests.

- [ ] **Step 3: Implement the import and the indexes**

In `app/utils/mongo_utils.py`, replace `importFromData` with:

```python
    def importFromData(self, data_to_import):
        documents = list(data_to_import)
        if not documents:
            return 0
        operations = [pymongo.ReplaceOne({'smid': doc['smid']}, doc, upsert=True)
                      for doc in documents]
        self.get_collection().bulk_write(operations, ordered=False)
        return len(documents)
```

Add after it:

```python
    def ensure_indexes(self):
        collection = self.get_collection()
        for field in ('smid', 'docdate'):
            try:
                collection.create_index(field)
            except Exception:
                pass
```

and call `self.ensure_indexes()` as the last line of `init_app`, after `self._client = pymongo.MongoClient(...)`.

The count is the number of submitted documents, not `upserted_count + modified_count`: a re-import of unchanged rows reports `modified_count == 0`, and the sync's row budget (Task 4) must count what was fetched, not what Mongo considered changed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python -m unittest tests.test_import_from_data -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Run the full suite**

Run: `cd app && python -m unittest discover tests`
Expected: `Ran 36 tests ... OK`.

- [ ] **Step 6: Commit**

```bash
git add app/utils/mongo_utils.py app/tests/test_import_from_data.py
git commit -m "fix(mongo): make movement imports idempotent and empty-safe"
```

---

### Task 3: `last_record()` is display-only and `None`-safe

**Files:**
- Modify: `app/utils/mongo_utils.py` (`MongoConfig` :11, `build_mongo_configuration` :27, `last_docnum` :72-80, `init_app` :121-124, `last_record` :160-165`)
- Test: `app/tests/test_last_record.py` (create)

**Interfaces:**
- Produces:
  - `last_movement_pipeline(date_format: str) -> tuple[list, dict]` — no `$match`; projects `docnum`, `docdate`, `timestamp` (`$dateToString` with `date_format`); `$sort {'docdate': -1}`; `$limit 1`. Replaces `last_docnum`.
  - `CacheDao.last_record() -> dict | None` — the record with `_id` removed, or `None` when the collection is empty.
  - `MongoConfig = namedtuple('MongoConfig', ['config', 'date_format'])` — the `sorting_id` field is gone, so `init_app` no longer sets `_sorting_id`.
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_last_record.py`:

```python
"""last_record() must never raise on an empty collection: the page header
and the sync both call it, so an IndexError there takes down the page."""
import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]  # .../app
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from utils.mongo_utils import CacheDao, last_movement_pipeline


class FakeDao(CacheDao):
    def __init__(self, rows):
        self._rows = rows
        self._date_format = '%Y-%m-%d %H:%M'

    def apply_aggregate(self, pipeline, options):
        return iter(self._rows)


class LastRecordTest(unittest.TestCase):
    def test_pipeline_reads_the_whole_collection_ordered_by_docdate(self):
        pipeline, _options = last_movement_pipeline('%Y-%m-%d %H:%M')

        self.assertEqual(pipeline[0], {'$project': {
            'docnum': 1,
            'docdate': 1,
            'timestamp': {'$dateToString': {'format': '%Y-%m-%d %H:%M',
                                            'date': '$docdate'}},
        }})
        self.assertNotIn('$match', [list(stage) for stage in pipeline])
        self.assertEqual(pipeline[1], {'$sort': {'docdate': -1}})
        self.assertEqual(pipeline[2], {'$limit': 1})

    def test_returns_none_for_an_empty_collection(self):
        self.assertIsNone(FakeDao([]).last_record())

    def test_returns_the_record_without_its_mongo_id(self):
        row = {'_id': 'abc', 'docnum': 10, 'timestamp': '2026-11-21 11:00'}
        self.assertEqual(FakeDao([row]).last_record(),
                         {'docnum': 10, 'timestamp': '2026-11-21 11:00'})


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python -m unittest tests.test_last_record -v`
Expected: FAIL — `ImportError: cannot import name 'last_movement_pipeline'`; `test_returns_none_for_an_empty_collection` would also fail with `IndexError` once the import is fixed.

- [ ] **Step 3: Implement**

In `app/utils/mongo_utils.py`:

1. `MongoConfig`: `namedtuple('MongoConfig', ['config','date_format'])`.
2. `build_mongo_configuration` returns `MongoConfig({...}, "%Y-%m-%d %H:%M")` (drop the `'smid'` argument).
3. Replace `last_docnum` with:

```python
def last_movement_pipeline(date_format: str):
    pipeline = [
        {"$project":{"docnum":1, "docdate":1,
                     "timestamp":{"$dateToString": {"format":date_format, "date":"$docdate"}}}},
        {"$sort":{"docdate":pymongo.DESCENDING}},
        {"$limit":1}
    ]
    options={}
    return pipeline, options
```

4. `init_app`: drop `self._sorting_id = app.sorting_id` (keep `self._date_format`).
5. Replace `last_record` with:

```python
    def last_record(self):
        rows = list(self.apply_aggregate(*last_movement_pipeline(self._date_format)))
        if not rows:
            return None
        record = rows[0]
        record.pop('_id', None)
        return record
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python -m unittest tests.test_last_record -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Prove nothing else used the removed cursor field**

Run: `cd app && grep -rn "sorting_id\|last_docnum" . --include=*.py`
Expected: no matches (the page's use of `last_record` is rewired in Task 5, which still compiles because `last_record` keeps its name).

- [ ] **Step 6: Run the full suite**

Run: `cd app && python -m unittest discover tests`
Expected: `Ran 39 tests ... OK`.

- [ ] **Step 7: Commit**

```bash
git add app/utils/mongo_utils.py app/tests/test_last_record.py
git commit -m "fix(mongo): make last_record window-free and empty-safe"
```

---

### Task 4: Watermark state and `sync_from_odoo`

**Files:**
- Modify: `app/utils/mongo_utils.py` (add `naive_utc_now`, `SYNC_STATE_COLLECTION`, `SyncResult`, `get_state_collection`, `get_sync_state`, `set_sync_state`, `sync_from_odoo`)
- Test: `app/tests/test_sync_from_odoo.py` (create)

**Interfaces:**
- Consumes: `CacheDao.importFromData(data) -> int` (Task 2), `getStartDateOfPeriod(from_date, periodInWeeks)` (existing), and the date branch of `fetch_data_from_odoo` (Task 1), injected as the `fetch` callable.
- Produces:
  - `naive_utc_now() -> datetime` — naive UTC clock.
  - `SYNC_STATE_COLLECTION = 'sync-state'`
  - `SyncResult = namedtuple('SyncResult', ['mode', 'imported', 'window_start', 'window_end', 'remaining_days', 'watermark_before', 'watermark_after'])`
  - `CacheDao.get_state_collection()` — the `sync-state` collection of the same database.
  - `CacheDao.get_sync_state() -> dict | None` — `{'_id': <collection name>, 'watermark': datetime, 'updated_at': datetime}`.
  - `CacheDao.set_sync_state(watermark: datetime) -> None` — `update_one({'_id': <collection name>}, {'$max': {'watermark': watermark}, '$set': {'updated_at': ...}}, upsert=True)`, so the watermark can never move backwards.
  - `CacheDao.sync_from_odoo(fetch=None, since=None, now=None, max_rows=1000, slice_days=14, overlap_hours=6) -> SyncResult`
    - `fetch(query: dict) -> list[dict]`; defaults to `od.fetch_data_from_odoo(self._odoo_cache, query)`.
    - `since` — naive UTC datetime for the rewind control; `None` for normal operation.
    - `now` — injectable clock, defaults to `naive_utc_now()`.
    - `mode` is `'no_new'` when `imported == 0`, otherwise `'heal'` (`since` given), `'bootstrap'` (no state document) or `'incremental'`.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_sync_from_odoo.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python -m unittest tests.test_sync_from_odoo -v`
Expected: FAIL — `AttributeError: 'FakeDao' object has no attribute 'sync_from_odoo'`.

- [ ] **Step 3: Implement the clock, the state document and the policy**

At module level in `app/utils/mongo_utils.py` (next to `MongoConfig`):

```python
SYNC_STATE_COLLECTION = 'sync-state'
SyncResult = namedtuple('SyncResult', ['mode', 'imported', 'window_start',
                                       'window_end', 'remaining_days',
                                       'watermark_before', 'watermark_after'])

def naive_utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
```

In `CacheDao`, add:

```python
    def get_state_collection(self):
        return self.get_client()[self.config[self.DB]][SYNC_STATE_COLLECTION]

    def get_sync_state(self):
        return self.get_state_collection().find_one({'_id': self.config[self.COLLECTION]})

    def set_sync_state(self, watermark: dt.datetime) -> None:
        self.get_state_collection().update_one(
            {'_id': self.config[self.COLLECTION]},
            {'$max': {'watermark': watermark}, '$set': {'updated_at': naive_utc_now()}},
            upsert=True)
```

`$max` is the never-backwards guarantee; do not replace it with `$set`.

Then the policy. `mode` is `'no_new'` when nothing was imported (checked last), so a stale watermark with an empty result still reports `no_new`:

```python
    def sync_from_odoo(self, fetch=None, since=None, now=None,
                       max_rows=1000, slice_days=14, overlap_hours=6):
        fetch = fetch or (lambda query: od.fetch_data_from_odoo(self._odoo_cache, query))
        now = now or naive_utc_now()
        state = self.get_sync_state()
        watermark_before = state['watermark'] if state else None

        if since is not None:
            start, mode = min(since, now), 'heal'
        elif state is None:
            start, mode = getStartDateOfPeriod(now, 10), 'bootstrap'
        else:
            start = state['watermark'] - dt.timedelta(hours=overlap_hours)
            mode = 'incremental'

        imported, cursor = 0, start
        while cursor < now and imported < max_rows:
            end = min(cursor + dt.timedelta(days=slice_days), now)
            imported += self.importFromData(fetch({'start_date': cursor, 'end_date': end}))
            cursor = end
            self.set_sync_state(cursor)

        final_state = self.get_sync_state()
        return SyncResult('no_new' if imported == 0 else mode, imported, start, cursor,
                          max(0, (now - cursor).days), watermark_before,
                          final_state['watermark'] if final_state else None)
```

Two ordering rules the tests pin: `set_sync_state(cursor)` comes **after** the write for that slice (a write failure leaves the watermark before the failed slice), and it comes **before** the loop condition is re-tested with `cursor` advanced even when the slice was empty (an empty fortnight cannot stall the catch-up).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python -m unittest tests.test_sync_from_odoo -v`
Expected: 8 tests PASS.

- [ ] **Step 5: Run the full suite**

Run: `cd app && python -m unittest discover tests`
Expected: `Ran 47 tests ... OK`.

- [ ] **Step 6: Commit**

```bash
git add app/utils/mongo_utils.py app/tests/test_sync_from_odoo.py
git commit -m "feat(mongo): sync movements by validation date on a stored watermark"
```

---

### Task 5: Wire the Suppliers page to the sync

**Files:**
- Modify: `app/reports/suppliers.py:14-19` (replace `update_mongo`), `:88` (header), plus the new controls and the result rendering
- Test: `app/tests/test_suppliers_sync_page.py` (create)

**Interfaces:**
- Consumes: `CacheDao.last_record()`, `CacheDao.get_sync_state()`, `CacheDao.sync_from_odoo(...)`, `SyncResult` (Tasks 2-4).
- Produces: page-level helpers `update_mongo(mongo_dao)`, `resync_since(mongo_dao, since)`, `render_sync_result(result)`.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_suppliers_sync_page.py` (same mocking pattern as `app/tests/test_discounts.py`: patch the Streamlit calls and the cached inits, then import the page module):

```python
"""Suppliers page: empty collection must render, and the buttons must sync."""
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python -m unittest tests.test_suppliers_sync_page -v`
Expected: FAIL — the page still calls `last_record()['docnum']`/`['timestamp']`, so `test_empty_collection_renders_and_says_never` raises `TypeError: 'NoneType' object is not subscriptable`, and `self.buttons['Mettre à jour mouvements']` lacks the expected callback name.

- [ ] **Step 3: Rewrite the page's sync wiring**

In `app/reports/suppliers.py`, replace `update_mongo` (lines 14-19) with:

```python
def update_mongo(mongo_dao):
    st.session_state['sync_result'] = mongo_dao.sync_from_odoo()

def resync_since(mongo_dao, since):
    st.session_state['sync_result'] = mongo_dao.sync_from_odoo(since=since)

def render_sync_result(result):
    if result is None:
        return
    if result.mode == 'no_new':
        st.info(f"Aucun nouveau mouvement (curseur {result.window_start:%Y-%m-%d}).")
    elif result.mode == 'bootstrap':
        st.success(f"Premier import : {result.imported} mouvements "
                   f"({result.window_start:%Y-%m-%d} → {result.window_end:%Y-%m-%d}).")
    elif result.remaining_days > 0:
        st.warning(f"{result.imported} mouvements importés "
                   f"({result.window_start:%Y-%m-%d} → {result.window_end:%Y-%m-%d}). "
                   f"Il reste {result.remaining_days} jours — relancez.")
    else:
        st.success(f"{result.imported} mouvements importés "
                   f"({result.window_start:%Y-%m-%d} → {result.window_end:%Y-%m-%d}).")
```

Replace the header line (line 88) and the button block with:

```python
last = mongo_dao.last_record()
state = mongo_dao.get_sync_state()
st.header("Last updated: " + (last['timestamp'] if last else "never (MongoDB empty)"))
st.caption("Dernière synchro: " + (f"{state['watermark']:%Y-%m-%d %H:%M}" if state else "jamais"))
st.button('Mettre à jour mouvements', on_click=update_mongo, args=[mongo_dao])
st.button('Mettre à jour stock', on_click=st.cache_resource.clear)
rewind_date = st.date_input(
    'Re-synchroniser depuis',
    value=mu.getStartDateOfPeriod(dt.datetime.now(), 10).date())
st.button('Re-synchroniser depuis cette date', on_click=resync_since,
          args=[mongo_dao, dt.datetime.combine(rewind_date, dt.time.min)])
render_sync_result(st.session_state.pop('sync_result', None))
```

Output written inside an `on_click` callback is discarded by the next rerun, hence the result travelling through `st.session_state` and being rendered in the page body.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python -m unittest tests.test_suppliers_sync_page -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Run the full suite**

Run: `cd app && python -m unittest discover tests`
Expected: `Ran 51 tests ... OK`.

- [ ] **Step 6: Commit**

```bash
git add app/reports/suppliers.py app/tests/test_suppliers_sync_page.py
git commit -m "feat(suppliers): sync page on the watermark with a rewind control"
```

---

### Task 6: Update the docs

**Files:**
- Modify: `docs/architecture.md` (caching table + the Suppliers data flow), `docs/pages.md` (Suppliers section), `docs/configuration.md` (collections and indexes)

**Interfaces:** none — documentation only.

- [ ] **Step 1: Update `docs/pages.md`, Suppliers section**

Replace the two update buttons' description with three controls and their messages:

```markdown
1. **Update buttons**
   - *Mettre à jour mouvements* — imports Odoo `stock.picking` records by
     `date_done`, in 14-day slices, up to 1000 rows per press; a long gap takes
     several presses and the message says how many days remain. Progress is
     stored in the `sync-state` collection (`watermark`).
   - *Mettre à jour stock* — clears the Streamlit caches so Odoo master data/stock
     is re-fetched.
   - *Re-synchroniser depuis cette date* — re-imports from the chosen date
     (default: the 10-week pivot anchor). Safe to repeat: rows are upserted on
     `smid`. Use it to recover movements missed by the old id-based sync,
     notably the remainder of a delivery split into several pickings.
```

- [ ] **Step 2: Update `docs/architecture.md`**

In the caching table, add:

```markdown
| Sync watermark (`sync-state`) | MongoDB document, `$max` update | Until overwritten by a later sync |
```

and after the Mongo row of the *Data flow* table add one line:

```markdown
Movements are fetched by validation date (`date_done`) on slices tracked by the
`sync-state` watermark, never by picking id — a backorder validated after a later
picking keeps an older id and would be invisible to an id cursor.
```

- [ ] **Step 3: Update `docs/configuration.md`**

Extend the MongoDB section:

```markdown
`raw-data` documents are upserted on `smid`, so re-imports never duplicate rows.
Two indexes are created on first use (`smid`, `docdate`); a **unique** index on
`smid` is recommended once existing duplicates have been cleaned up, but is left
to the operator because creating it fails while duplicates exist.

The `sync-state` collection holds one document per synced collection
(`_id: raw-data`) with the last `date_done` covered (`watermark`) and the last
successful update time (`updated_at`). Deleting it makes the next press
re-import from the 10-week anchor, which is safe but slow.
```

- [ ] **Step 4: Verify the docs render as valid markdown**

Run: `cd /Users/chinois/localDocuments/python/git/order-assistant && grep -n "sync-state\|watermark\|date_done" docs/*.md`
Expected: matches in all three files.

- [ ] **Step 5: Commit**

```bash
git add docs/architecture.md docs/pages.md docs/configuration.md
git commit -m "docs: describe the validation-date sync and the watermark"
```

---

## Notes for the executor

- Do not touch `get_stock_pickings_after_id`; it stays for manual use and for the `{'picking_id': …}` branch Task 1 keeps alive.
- `report_builder.py`, `history.py`, `warehouses.py`, `forecast.py` need no change: they read `raw-data`, not the cursor (verified: only `reports/suppliers.py` calls `last_record`/`importFromData`).
- After the fix, an existing installation's already-missed backorders stay missed until someone presses *Re-synchroniser depuis cette date* with the default 10-week anchor.
