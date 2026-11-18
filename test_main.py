import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import main


def component(code=10, quantity='1', unit='KG'):
    return dict(CODPROD=code, QT=Decimal(quantity), UNESTRUTURA=unit,
                NUMETAPA=1, FRACAOUMIDA=0, METODO='1')


def write_fake_oci(directory, machine):
    header = bytearray(0x80)
    header[:2] = b'MZ'
    header[0x3C:0x40] = (0x40).to_bytes(4, 'little')
    header[0x40:0x44] = b'PE\0\0'
    header[0x44:0x46] = machine.to_bytes(2, 'little')
    (directory / 'oci.dll').write_bytes(header)


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
                elif sql.lstrip().startswith('DELETE'):
                    self.rowcount = 1
                elif sql.lstrip().startswith('UPDATE'):
                    self.rowcount = 1
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
                        patch.object(main, 'show_info')]
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

    def test_selected_source_components_replace_entire_destination_structure(self):
        self.assertTrue(main.oracledb.defaults.fetch_decimals)
        self.assertFalse(self.w.windowIcon().isNull())
        self.assertEqual(self.w.windowTitle(), 'Clonar Estrutura de Produto')
        first_source = component(code=10, quantity='2.5')
        second_source = component(code=11, quantity='3.5')
        self.w.source = [first_source, second_source]
        self.w.source_snapshot = self.w.fingerprint(self.w.source)
        self.w.target = [
            component(code=10, quantity='1'),
            component(code=11, quantity='2'),
            component(code=12, quantity='4'),
        ]
        self.w.snapshot = self.w.fingerprint(self.w.target)
        self.w.populate()
        self.w.source_table.item(1, 0).setCheckState(main.Qt.Unchecked)

        plan=self.w.build_plan()
        self.assertEqual(plan['updates'],[
            {'index':0,'row':dict(first_source,METODO=self.w.method.currentText().strip())}
        ])
        self.assertEqual(plan['removals'],[1,2])
        self.assertEqual(plan['inserts'],[])
        self.assertEqual(self.w.target_table.columnCount(),6)
        self.assertEqual(self.w.target_table.horizontalHeaderItem(0).text(),'Código')
        self.assertFalse(
            self.w.target_table.item(0, 0).flags() & main.Qt.ItemIsUserCheckable
        )

    def test_empty_source_selection_still_plans_removal_of_existing_structure(self):
        self.configure_target(component())
        self.w.source_table.item(0, 0).setCheckState(main.Qt.Unchecked)
        plan = self.w.build_plan()
        self.assertEqual(plan['removals'], [0])
        self.assertEqual(plan['inserts'], [])
        self.assertEqual(plan['updates'], [])


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
        self.w.conn = Connection(self.w.source, self.w.target)
        self.w.fetch = lambda *args: [component(quantity='6')]
        self.w.commit(self.batch(), self.operation())
        self.assertEqual(self.w.conn.commits, 1)
        writes=[statement[0].lstrip().split(None,1)[0] for statement in self.w.conn.statements
                if statement[0].lstrip().startswith(('DELETE','UPDATE','INSERT'))]
        self.assertEqual(writes,['UPDATE'])
        self.assertTrue(self.w.operation_completed)
        self.assertEqual(self.w.source_table.item(0, 0).checkState(), main.Qt.Unchecked)
        self.assertFalse(self.w.confirm.isEnabled())
        with self.assertRaisesRegex(ValueError, 'já foi concluída'): self.w.build_plan()
        self.w.source_table.item(0, 0).setCheckState(main.Qt.Checked)
        self.assertFalse(self.w.operation_completed)

    def test_commit_updates_matching_and_removes_unselected_destination_rows(self):
        self.w.source = [component(code=10), component(code=11)]
        self.w.target = [component(code=10), component(code=11), component(code=12)]
        self.w.source_snapshot = self.w.fingerprint(self.w.source)
        self.w.snapshot = self.w.fingerprint(self.w.target)
        self.w.populate()
        self.w.source_table.item(1, 0).setCheckState(main.Qt.Unchecked)
        self.w.conn = Connection(self.w.source, self.w.target)
        self.w.load_origin = lambda: None
        self.w.load_destination = lambda: None

        self.w.commit(self.batch(), self.operation())

        writes = [statement for statement in self.w.conn.statements
                  if statement[0].lstrip().startswith(('DELETE', 'INSERT'))]
        self.assertEqual([statement[0].lstrip().split(None, 1)[0] for statement in writes],
                         ['DELETE', 'DELETE'])
        updates=[statement for statement in self.w.conn.statements
                 if statement[0].lstrip().startswith('UPDATE')]
        self.assertEqual(len(updates),1)
        self.assertIn('CODPROD=:c',updates[0][0])
        quantity_bind=f'u{main.COPY_FIELDS.index("QT")}'
        self.assertEqual(updates[0][1][0][quantity_bind],Decimal('1'))
        self.assertEqual(self.w.conn.commits, 1)

    def test_matching_destination_key_is_updated_not_deleted_and_reinserted(self):
        self.w.source = [component(code=10, quantity='9')]
        self.w.source_snapshot = self.w.fingerprint(self.w.source)
        self.configure_target(component(code=10, quantity='1'))
        self.w.conn = Connection(self.w.source, self.w.target)

        self.w.commit(self.batch(), self.operation())

        writes=[statement[0].lstrip().split(None,1)[0]
                for statement in self.w.conn.statements
                if statement[0].lstrip().startswith(('DELETE','UPDATE','INSERT'))]
        self.assertEqual(writes,['UPDATE'])
        update=next(statement for statement in self.w.conn.statements
                    if statement[0].lstrip().startswith('UPDATE'))
        quantity_bind=f'u{main.COPY_FIELDS.index("QT")}'
        self.assertEqual(update[1][0][quantity_bind],Decimal('9'))
        self.assertEqual(self.w.conn.commits,1)


class OracleConnectionModeTests(unittest.TestCase):
    def test_winthor_connection_uses_bundled_thick_client(self):
        winthor = {
            'usuario_bd': 'oracle-user',
            'senha_bd': 'oracle-password',
            'alias_bd': 'ORCL',
        }
        client_dir = Path('C:/app/oracle_client')
        config_dir = Path('C:/oracle/network/admin')
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(main, 'find_tns_directory', return_value=config_dir), \
                patch.object(main, 'find_oracle_client_dir', return_value=client_dir), \
                patch.object(main.oracledb, 'init_oracle_client') as init_client, \
                patch.object(main.oracledb, 'connect') as connect:
            connection, mode = main.open_oracle_connection(winthor)

        self.assertIs(connection, connect.return_value)
        self.assertEqual(mode, 'thick')
        init_client.assert_called_once_with(
            lib_dir=str(client_dir),
            config_dir=str(config_dir))
        connect.assert_called_once_with(
            user='oracle-user',
            password='oracle-password',
            dsn='ORCL',
            program='RB1601')

    def test_winthor_connection_requires_compatible_client(self):
        winthor = {
            'usuario_bd': 'oracle-user',
            'senha_bd': 'oracle-password',
            'alias_bd': 'ORCL',
        }
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(main, 'find_oracle_client_dir', return_value=None), \
                patch.object(main.oracledb, 'init_oracle_client') as init_client:
            with self.assertRaisesRegex(FileNotFoundError, 'Oracle Client compatível'):
                main.open_oracle_connection(winthor)
        init_client.assert_not_called()

    def test_bundled_oracle_client_is_discovered(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_dir = Path(temp_dir)
            client_dir = bundle_dir / 'oracle_client'
            client_dir.mkdir()
            write_fake_oci(client_dir, 0x8664)
            with patch.dict(os.environ, {}, clear=True), \
                    patch.object(main.sys, '_MEIPASS', str(bundle_dir), create=True), \
                    patch.object(main, 'BASE_DIR', bundle_dir / 'app'):
                self.assertEqual(
                    main.find_oracle_client_dir(),
                    client_dir.resolve())

    def test_oracle_client_is_discovered_from_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client_dir = Path(temp_dir)
            write_fake_oci(client_dir, 0x8664)
            with patch.dict(os.environ, {'PATH': temp_dir}, clear=True), \
                    patch.object(main, 'BASE_DIR', client_dir / 'app'):
                self.assertEqual(main.find_oracle_client_dir(), client_dir.resolve())

    def test_oracle_client_discovery_skips_incompatible_x86_client(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            x86_client = root / 'client32'
            x64_client = root / 'client64'
            x86_client.mkdir()
            x64_client.mkdir()
            write_fake_oci(x86_client, 0x14C)
            write_fake_oci(x64_client, 0x8664)
            with patch.dict(os.environ, {'PATH': str(x64_client)}, clear=True), \
                    patch.object(main, 'BASE_DIR', root / 'app'):
                self.assertEqual(
                    main.find_oracle_client_dir(str(x86_client)),
                    x64_client.resolve())

    def test_configured_oracle_client_path_takes_precedence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client_dir = Path(temp_dir) / 'oracle-client'
            client_dir.mkdir()
            write_fake_oci(client_dir, 0x8664)
            with patch.dict(os.environ, {}, clear=True), \
                    patch.object(main, 'BASE_DIR', Path(temp_dir) / 'app'):
                self.assertEqual(
                    main.find_oracle_client_dir(str(client_dir)),
                    client_dir.resolve())

    def test_auto_uses_thin_when_oracle_client_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            (config_dir / 'tnsnames.ora').write_text('ORCL = (DESCRIPTION=())', encoding='ascii')
            env = {
                'TNS_ADMIN': temp_dir,
                'ORACLE_USER': 'oracle-user',
                'ORACLE_PASSWORD': 'oracle-password',
                'ORACLE_DSN': 'ORCL',
            }
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(main, 'BASE_DIR', config_dir), \
                    patch.object(main, 'find_oracle_client_dir', return_value=None), \
                    patch.object(main.oracledb, 'init_oracle_client',
                                 side_effect=main.oracledb.DatabaseError('DPI-1047: client not found')) as init_client, \
                    patch.object(main.oracledb, 'connect') as connect:
                connection, mode = main.open_oracle_connection()

            self.assertEqual(mode, 'thin')
            self.assertIs(connection, connect.return_value)
            init_client.assert_called_once_with(config_dir=str(config_dir.resolve()))
            self.assertEqual(connect.call_args.kwargs['config_dir'], str(config_dir.resolve()))

    def test_tns_directory_is_found_from_alias_in_tnsnames_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            (config_dir / 'tnsnames.ora').write_text(
                'OTHER = (DESCRIPTION=())\nORCL = (DESCRIPTION=())\n',
                encoding='ascii')
            with patch.dict(os.environ, {'TNS_ADMIN': temp_dir}, clear=True):
                self.assertEqual(main.find_tns_directory('ORCL'), config_dir)
                self.assertIsNone(main.find_tns_directory('UNKNOWN'))

    def test_thin_alias_without_tns_file_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                'ORACLE_USER': 'oracle-user',
                'ORACLE_PASSWORD': 'oracle-password',
                'ORACLE_DSN': 'ORCL',
            }
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(main, 'BASE_DIR', Path(temp_dir)), \
                    patch.object(main, 'find_oracle_client_dir', return_value=None), \
                    patch.object(main.oracledb, 'init_oracle_client',
                                 side_effect=main.oracledb.DatabaseError('DPI-1047: client not found')), \
                    patch.object(main.oracledb, 'connect') as connect:
                with self.assertRaisesRegex(FileNotFoundError, 'tnsnames.ora.*ORCL'):
                    main.open_oracle_connection()
            connect.assert_not_called()

    def test_auto_uses_local_oracle_client_when_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            client_dir = base_dir / 'oracle_client'
            client_dir.mkdir()
            write_fake_oci(client_dir, 0x8664)
            env = {
                'ORACLE_USER': 'oracle-user',
                'ORACLE_PASSWORD': 'oracle-password',
                'ORACLE_DSN': 'ORCL',
            }
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(main, 'BASE_DIR', base_dir), \
                    patch.object(main.oracledb, 'init_oracle_client') as init_client, \
                    patch.object(main.oracledb, 'connect') as connect:
                _, mode = main.open_oracle_connection()

            self.assertEqual(mode, 'thick')
            init_client.assert_called_once_with(lib_dir=str(client_dir.resolve()))
            self.assertNotIn('config_dir', connect.call_args.kwargs)

    def test_auto_falls_back_to_thin_when_client_cannot_be_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            client_dir = base_dir / 'oracle_client'
            client_dir.mkdir()
            write_fake_oci(client_dir, 0x8664)
            (base_dir / 'tnsnames.ora').write_text('ORCL = (DESCRIPTION=())', encoding='ascii')
            env = {
                'TNS_ADMIN': temp_dir,
                'ORACLE_USER': 'oracle-user',
                'ORACLE_PASSWORD': 'oracle-password',
                'ORACLE_DSN': 'ORCL',
            }
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(main, 'BASE_DIR', base_dir), \
                    patch.object(main, 'find_oracle_client_dir', return_value=client_dir.resolve()), \
                    patch.object(main.oracledb, 'init_oracle_client',
                                 side_effect=main.oracledb.DatabaseError('DPI-1047: client cannot load')) as init_client, \
                    patch.object(main.oracledb, 'connect') as connect:
                _, mode = main.open_oracle_connection()

            self.assertEqual(mode, 'thin')
            init_client.assert_called_once_with(
                lib_dir=str(client_dir.resolve()), config_dir=str(base_dir.resolve()))
            self.assertEqual(connect.call_args.kwargs['config_dir'], str(base_dir.resolve()))


if __name__ == '__main__':
    unittest.main()
