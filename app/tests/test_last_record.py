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
