import os
os.environ['DOUBAN_USER_ID'] = 'example_user'
"""Offline publishing uses only synthetic source archives."""
import json
from pathlib import Path
import tempfile
import unittest

from delivery import load_delivery
from publish_existing import run
from test_consolidate import snapshot


class ExistingPublicationTests(unittest.TestCase):
    def test_prior_outputs_and_raw_are_preserved_and_repeat_is_fixed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);raw=root/'data/raw/synthetic/snapshot.json';raw.parent.mkdir(parents=True)
            raw.write_text(json.dumps(snapshot('2026-01-01T00:00:00+08:00',[{'douban_id':'123','title':'Synthetic film'}])))
            original=raw.read_bytes();legacy=root/'outputs/example_user/douban_master.json';legacy.parent.mkdir(parents=True);legacy.write_bytes(b'preserved previous output')
            first=run(root);second=run(root)
            self.assertEqual(first['receipt_sha256'],second['receipt_sha256'])
            self.assertEqual(raw.read_bytes(),original);self.assertEqual(legacy.read_bytes(),b'preserved previous output')
            self.assertEqual((Path(first['previous_outputs'])/legacy.name).read_bytes(),legacy.read_bytes())
            self.assertEqual(load_delivery(first['directory'],expected_receipt_sha256=first['receipt_sha256'])['receipt']['record_count'],1)


if __name__=='__main__':unittest.main()
