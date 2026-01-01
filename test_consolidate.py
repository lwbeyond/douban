import os
os.environ['DOUBAN_USER_ID'] = 'example_user'
import unittest
from consolidate import merge_snapshots, csv_safe


def snapshot(date, items, category='movies', status='wish', complete=True):
    return {'metadata': {'user_id': 'example_user', 'generated_at': date, 'backup_mode': 'public'},
            'data': {category: {status: items}},
            'coverage': {category: {status: {'pagination_complete': complete, 'count_matches': True}}}}


class ImportTests(unittest.TestCase):
    def test_book_date_does_not_include_status_text(self):
        data=snapshot('2026-01-01T00:00:00+08:00',[{'douban_id':'123','date':'2024-04-11\n 想读'}],'books')
        rows,_=merge_snapshots([('a',data)])
        self.assertEqual(rows[0]['marked_at'],'2024-04-11')

    def test_repeated_import_updates_status_and_explicitly_cleared_fields(self):
        old = snapshot('2026-01-01T00:00:00+08:00', [{'douban_id':'123', 'title':'A', 'rating':'5', 'comment':'old'}])
        new = snapshot('2026-02-01T00:00:00+08:00', [{'douban_id':'123', 'title':'A', 'rating':'', 'comment':''}], status='collect')
        rows, _ = merge_snapshots([('b', new), ('a', old), ('b', new)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'collect')
        self.assertIsNone(rows[0]['rating'])
        self.assertEqual(rows[0]['comment'], '')
        self.assertEqual(rows[0]['first_seen_at'], old['metadata']['generated_at'])

    def test_cross_category_ids_and_multiple_reviews_remain_distinct(self):
        inputs = [(str(i),snapshot('2026-01-01T00:00:00+08:00',items,category,status)) for i,(category,status,items) in enumerate([
            ('movies','collect',[{'douban_id':'123','title':'Same'}]),
            ('books','collect',[{'douban_id':'123','title':'Same'}]),
            ('reviews','collect',[{'douban_id':'123','subject_id':'123'}, {'douban_id':'456','subject_id':'123'}])])]
        rows,_ = merge_snapshots(inputs)
        self.assertEqual(len(rows),4)

    def test_partial_and_empty_snapshots_never_erase_records(self):
        old=snapshot('2026-01-01T00:00:00+08:00',[{'douban_id':'123','title':'A'}])
        partial=snapshot('2026-02-01T00:00:00+08:00',[{'douban_id':'123','title':'broken'}],complete=False)
        empty=snapshot('2026-03-01T00:00:00+08:00',[])
        rows,_=merge_snapshots([('a',old),('b',partial),('c',empty)])
        self.assertEqual(rows[0]['title'],'A')

    def test_missing_id_is_quarantined_and_wrong_user_rejected(self):
        data=snapshot('2026-01-01T00:00:00+08:00',[{'title':'Missing'}])
        rows,report=merge_snapshots([('a',data)])
        self.assertEqual(rows,[])
        self.assertEqual(len(report['rejected']),1)
        data['metadata']['user_id']='Other'
        with self.assertRaises(ValueError): merge_snapshots([('a',data)])

    def test_full_review_is_not_overwritten_by_failed_body_fetch(self):
        old=snapshot('2026-01-01T00:00:00+08:00',[{'douban_id':'123','comment':'full\nbody','text_complete':True}],'reviews','collect')
        new=snapshot('2026-02-01T00:00:00+08:00',[{'douban_id':'123','comment':'summary','text_complete':False}],'reviews','collect')
        rows,_=merge_snapshots([('a',old),('b',new)])
        self.assertEqual(rows[0]['comment'],'full\nbody')

    def test_csv_formula_text_and_multiline_content(self):
        self.assertEqual(csv_safe('=1+1'), "'=1+1")
        self.assertEqual(csv_safe('  @SUM(A1)'), "'  @SUM(A1)")
        self.assertEqual(csv_safe('第一行\n第二行'),'第一行\n第二行')


if __name__ == '__main__': unittest.main()
