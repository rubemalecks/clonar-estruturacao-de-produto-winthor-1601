import os
import unittest
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import main


def component(code=10, quantity='1', unit='KG'):
    return dict(CODPROD=code, QT=Decimal(quantity), UNESTRUTURA=unit,
                NUMETAPA=1, FRACAOUMIDA=0, METODO='1')


class Connection:
    def __init__(self, source, target, fail_write=False, fail_rollback=False):
        self.source, self.target = source, target
        self.fail_write, self.fail_rollback = fail_write, fail_rollback
        self.statements = []
        self.commits = self.rollbacks = 0

    def cursor(self):
        connection = self

        class Cursor:
            description = [(name,) for name in main.FIELDS]
            rowcount = 1

            def __enter__(self): return self
            def __exit__(self, *args): pass

            def execute(self, sql, *args, **kwargs):
                connection.statements.append((sql, args, kwargs))
                if sql.lstrip().startswith('SELECT'):
                    self.rows = connection.source if kwargs['p'] == 100 else connection.target
                elif connection.fail_write:
                    raise RuntimeError('original write failure')

            def __iter__(self):
                return iter(tuple(row.get(name) for name in main.FIELDS) for row in self.rows)

        return Cursor()

    def commit(self): self.commits += 1

    def rollback(self):
        self.rollbacks += 1
        if self.fail_rollback: raise RuntimeError('rollback failure')


class CopySafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = main.QApplication.instance() or main.QApplication([])

    def setUp(self):
        self.patches = [patch.object(main.App, 'connect_db', lambda self: None),
                        patch.object(main, 'show_alert'), patch.object(main, 'show_error'),
                        patch.object(main.QMessageBox, 'information')]
        self.mocks = [p.start() for p in self.patches]
        self.w = main.App()
        for field in (self.w.origin_branch, self.w.dest_branch):
            with main.QSignalBlocker(field): field.addItem('1', '1')
        self.w.origin.code, self.w.dest.code = 100, 200
        with main.QSignalBlocker(self.w.origin_method):
            self.w.origin_method.addItem('1', '1')
        self.w.source, self.w.target = [component()], []
        self.w.origin_loaded = True
        self.w.source_snapshot = self.w.fingerprint(self.w.source)
        self.w.snapshot = self.w.fingerprint(self.w.target)
        self.w.populate()

    def tearDown(self):
        self.w.dest_timer.stop()
        self.w.close()
        self.w.deleteLater()
        self.qt.processEvents()
        for p in reversed(self.patches): p.stop()

    def configure_target(self, row):
        self.w.target = [row]
        self.w.snapshot = self.w.fingerprint(self.w.target)
        self.w.populate()

    def operation(self):
        return dict(product=200, method='1', source_product=100,
                    source_branch='1', source_method='1', source_snapshot=self.w.source_snapshot)

    def batch(self):
        return [dict(branch='1', target=self.w.target, snapshot=self.w.snapshot,
                     plan=self.w.build_plan())]

    def test_decimal_fetch_and_exact_sum(self):
        self.assertTrue(main.oracledb.defaults.fetch_decimals)
        self.configure_target(component(quantity='1'))
        self.w.source[0]['QT'] = Decimal('0.12345678901234567890123456789')
        self.w.sum.setChecked(True)
        self.assertEqual(self.w.build_plan()['updates'][0],
                         Decimal('1.12345678901234567890123456789'))

    def test_excess_oracle_precision_is_rejected(self):
        with self.assertRaises(ValueError): main.exact_quantity_sum('1', '1e-40')

    def test_mismatched_units_block_sum_and_replace(self):
        self.configure_target(component(unit='SC'))
        for policy in (self.w.replace, self.w.sum):
            policy.setChecked(True)
            with self.assertRaisesRegex(ValueError, 'unidades incompat'):
                self.w.build_plan()

    def test_ignore_does_not_modify_mismatched_units(self):
        self.configure_target(component(unit='SC'))
        self.assertFalse(self.w.build_plan()['updates'])

    def test_self_reference_requires_deselecting_component(self):
        self.w.source[0]['CODPROD'] = 200
        with self.assertRaisesRegex(ValueError, 'própria composição'):
            self.w.build_plan()
        self.w.source_table.item(0, 0).setCheckState(main.Qt.Unchecked)
        self.assertFalse(self.w.build_plan()['inserts'])

    def test_same_product_and_branch_accept_only_new_method(self):
        self.w.dest.code = 100
        with main.QSignalBlocker(self.w.method): self.w.method.setEditText('B')
        self.assertEqual(len(self.w.build_plan()['inserts']), 1)
        self.configure_target(component())
        with self.assertRaisesRegex(ValueError, 'método novo'): self.w.build_plan()

    def test_same_source_method_is_rejected(self):
        self.w.dest.code = 100
        with self.assertRaisesRegex(ValueError, 'método novo'): self.w.build_plan()

    def test_changed_source_prevents_all_writes(self):
        self.w.conn = Connection([component(quantity='2')], [])
        self.w.load_origin = lambda: None
        self.w.load_destination = lambda: None
        self.w.commit(self.batch(), self.operation())
        self.assertEqual(self.w.conn.commits, 0)
        self.assertEqual(self.w.conn.rollbacks, 1)
        self.assertEqual(len(self.w.conn.statements), 1)
        self.assertFalse(self.w.confirm.isEnabled())
        self.assertIn('origem', self.mocks[1].call_args.args[2])

    def test_changed_target_prevents_all_writes(self):
        self.w.conn = Connection(self.w.source, [component()])
        self.w.load_origin = lambda: None
        self.w.load_destination = lambda: None
        self.w.commit(self.batch(), self.operation())
        self.assertEqual(self.w.conn.commits, 0)
        self.assertEqual(self.w.conn.rollbacks, 1)
        self.assertIn('destino', self.mocks[1].call_args.args[2])

    def test_rollback_failure_preserves_both_errors_and_blocks_retry(self):
        self.w.conn = Connection(self.w.source, [], fail_write=True, fail_rollback=True)
        self.w.commit(self.batch(), self.operation())
        self.assertTrue(self.w.connection_uncertain)
        text = self.mocks[2].call_args.args[2]
        self.assertIn('original write failure', text)
        self.assertIn('rollback failure', text)
        self.assertFalse(self.w.confirm.isEnabled())

    def test_write_failure_rolls_back(self):
        self.w.conn = Connection(self.w.source, [], fail_write=True)
        self.w.commit(self.batch(), self.operation())
        self.assertEqual(self.w.conn.rollbacks, 1)
        self.assertFalse(self.w.connection_uncertain)

    def test_commit_failure_blocks_retry_even_if_rollback_succeeds(self):
        self.w.conn = Connection(self.w.source, [])
        def failed_commit(): raise RuntimeError('commit response lost')
        self.w.conn.commit = failed_commit
        self.w.commit(self.batch(), self.operation())
        self.assertTrue(self.w.connection_uncertain)
        self.assertFalse(self.w.confirm.isEnabled())
        self.assertIn('commit response lost', self.mocks[2].call_args.args[2])

    def test_source_insert_during_write_prevents_commit(self):
        self.w.conn = Connection(list(self.w.source), [])
        original_cursor = self.w.conn.cursor
        def cursor():
            cur = original_cursor()
            execute = cur.execute
            def changing_execute(sql, *args, **kwargs):
                execute(sql, *args, **kwargs)
                if sql.startswith('INSERT'):
                    self.w.conn.source.append(component(11))
            cur.execute = changing_execute
            return cur
        self.w.conn.cursor = cursor
        self.w.load_origin = lambda: None
        self.w.load_destination = lambda: None
        self.w.commit(self.batch(), self.operation())
        self.assertEqual(self.w.conn.commits, 0)
        self.assertEqual(self.w.conn.rollbacks, 1)

    def test_success_finishes_operation_and_blocks_repeat(self):
        self.configure_target(component(quantity='5'))
        self.w.sum.setChecked(True)
        self.w.conn = Connection(self.w.source, self.w.target)
        self.w.fetch = lambda *args: [component(quantity='6')]
        self.w.commit(self.batch(), self.operation())
        self.assertEqual(self.w.conn.commits, 1)
        self.assertTrue(self.w.operation_completed)
        self.assertEqual(self.w.source_table.item(0, 0).checkState(), main.Qt.Unchecked)
        self.assertFalse(self.w.confirm.isEnabled())
        with self.assertRaisesRegex(ValueError, 'já foi concluída'): self.w.build_plan()
        self.w.source_table.item(0, 0).setCheckState(main.Qt.Checked)
        self.assertFalse(self.w.operation_completed)


if __name__ == '__main__':
    unittest.main()
