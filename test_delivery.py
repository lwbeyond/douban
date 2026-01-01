import os
os.environ['DOUBAN_USER_ID'] = 'example_user'
"""Synthetic source-provider examples for knowledge-base consumption."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import delivery as d
from consolidate import merge_snapshots
from test_consolidate import snapshot


def example_inputs():
    old = snapshot('2026-01-01T00:00:00+08:00', [{'douban_id': '123', 'title': 'Synthetic source', 'comment': '', 'tags': []}])
    partial = snapshot('2026-02-01T00:00:00+08:00', [{'douban_id': '123', 'title': 'Incomplete'}], complete=False)
    cleared = snapshot('2026-03-01T00:00:00+08:00', [{'douban_id': '123', 'title': 'Synthetic source', 'rating': '', 'comment': ''}], status='collect')
    empty = snapshot('2026-04-01T00:00:00+08:00', [])
    return [(str(i) + '/snapshot.json', payload) for i, payload in enumerate([old, partial, cleared, empty])]


class DeliveryTests(unittest.TestCase):
    def make(self):
        inputs = example_inputs()
        rows, report = merge_snapshots(inputs)
        master = {'schema_version': 1, 'source': 'douban', 'user_id': 'example_user', 'record_count': len(rows),
                  'last_snapshot_at': '2026-04-01T00:00:00+08:00', 'records': rows}
        return master, report, [(name, d.encode(data)) for name, data in inputs]

    def test_partial_unseen_empty_clear_and_repeat_are_distinct(self):
        master, report, inputs = self.make()
        with tempfile.TemporaryDirectory() as temp:
            first = d.publish_delivery(temp, master, report, inputs)
            self.assertEqual(first, d.publish_delivery(temp, master, report, inputs))
            value = d.load_delivery(first['directory'], expected_receipt_sha256=first['receipt_sha256'])
            states = {row['scope_status'] for row in value['receipt']['lists']}
            self.assertTrue({'complete', 'partial', 'unseen', 'complete_empty'} <= states)
            self.assertEqual(value['douban_master.json']['record_count'], 1)
            self.assertEqual(value['douban_master.json']['records'][0]['title'], 'Synthetic source')
            self.assertIsNone(value['douban_master.json']['records'][0]['rating'])
            self.assertTrue(all(row['list_finished_at'] is None for row in value['receipt']['lists']))
            self.assertTrue(all(not row['can_update_rows'] for row in value['receipt']['lists'] if row['scope_status'] == 'partial'))

    def test_failed_pointer_preserves_previous_and_corrupt_bundle_rejected(self):
        master, report, inputs = self.make()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            first = d.publish_delivery(output, master, report, inputs)
            before = (output / 'current.json').read_bytes()
            with patch.object(d, 'atomic', side_effect=OSError('synthetic interrupted publication')):
                with self.assertRaises(OSError): d.publish_delivery(output, master, report, inputs)
            self.assertEqual((output / 'current.json').read_bytes(), before)
            path = Path(first['directory']) / 'douban_master.json'
            path.write_bytes(path.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                d.load_delivery(first['directory'], expected_receipt_sha256=first['receipt_sha256'])

    def test_machine_schema_and_account_namespace(self):
        self.assertEqual(json.loads((Path(__file__).parent / 'master.schema.json').read_bytes()), d.schema())
        master, _, _ = self.make()
        master['records'][0]['record_id'] = 'douban:SomeoneElse:movie:123'
        with self.assertRaisesRegex(ValueError, 'identity'): d.validate_master(master)
