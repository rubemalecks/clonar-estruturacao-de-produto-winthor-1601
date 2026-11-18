"""RB Formulações 1601 - copiar composição WinThor com prévia e transação."""
import os
import re
import struct
import sys
from collections import Counter
from pathlib import Path
from dotenv import load_dotenv
from decimal import Decimal
from PySide6.QtCore import Qt, QTimer, Signal, QSignalBlocker, QRegularExpression, QStringListModel
from PySide6.QtGui import QRegularExpressionValidator, QKeySequence, QColor, QPen, QPainter, QPainterPath, QPixmap, QIcon
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,
 QLineEdit,QPushButton,QLabel,QTableWidget,QTableWidgetItem,QMessageBox,QComboBox,QCheckBox,
 QSplitter,QHeaderView,QAbstractItemView,QInputDialog,QDialog,QDialogButtonBox,QGroupBox,QFrame,QSizePolicy,QCompleter,QProxyStyle,QStyle)
import oracledb

# Oracle NUMBER deve chegar como Decimal, antes de qualquer exibição ou cálculo.
oracledb.defaults.fetch_decimals = True

BASE_DIR = Path(getattr(sys, "executable", __file__)).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
ASSETS_DIR = Path(getattr(sys, '_MEIPASS', BASE_DIR)) / 'assets'
APP_ICON_PATH = ASSETS_DIR / 'rb_app_icon.png'

ALERT_STYLES = '''
    QMessageBox { background:#f4f8fc; color:#172b3a; font-size:13px; }
    QMessageBox QLabel { color:#172b3a; background:transparent; font-size:13px; }
    QMessageBox QLabel#qt_msgbox_label { font-weight:600; min-width:300px; }
    QMessageBox QPushButton { background:#0065a8; color:white; border:1px solid #004e82;
        border-radius:4px; padding:7px 16px; min-width:75px; font-size:13px; }
    QMessageBox QPushButton:hover { background:#00548d; }
    QMessageBox QPushButton:focus { border:2px solid #173c58; }
    QMessageBox QTextEdit { background:white; color:#172b3a; }
'''


def show_alert(parent,title,message,icon=QMessageBox.Warning):
    dialog=QMessageBox(parent)
    dialog.setStyleSheet(ALERT_STYLES)
    dialog.setIcon(icon)
    dialog.setWindowTitle(title)
    dialog.setTextFormat(Qt.PlainText)
    message=str(message)
    uncertain_titles=('Conexão interrompida','Resultado da gravação não confirmado','Atualização da tela')
    if title not in uncertain_titles and any(code in message for code in ('ORA-','DPI-','DPY-')):
        dialog.setText('Não foi possível concluir a operação\nno banco de dados.')
        dialog.setInformativeText(
            'Confira a conexão e tente novamente.\nConsulte os detalhes do erro abaixo.'
        )
        dialog.setDetailedText(message)
        details_button=next(
            (button for button in dialog.findChildren(QPushButton)
             if button.text() in ('Show Details...','Hide Details...')),
            None,
        )
        if details_button is not None:
            expanded=[False]
            details_button.setText('Mostrar detalhes')
            def toggle_details():
                expanded[0]=not expanded[0]
                details_button.setText('Ocultar detalhes' if expanded[0] else 'Mostrar detalhes')
            details_button.clicked.connect(toggle_details)
    else:
        dialog.setText(message)
    if title=='Operação cancelada (ROLLBACK)':
        dialog.setInformativeText(
            'As alterações desta operação foram desfeitas.\nRevise os dados antes de tentar novamente.'
        )
    dialog.setStandardButtons(QMessageBox.Ok)
    dialog.button(QMessageBox.Ok).setText('Entendi')
    dialog.exec()


def show_error(parent,title,message):
    show_alert(parent,title,message,QMessageBox.Critical)


def show_info(parent,title,message):
    dialog=QMessageBox(parent)
    dialog.setStyleSheet(ALERT_STYLES)
    dialog.setIcon(QMessageBox.Information)
    dialog.setWindowTitle(title)
    dialog.setTextFormat(Qt.PlainText)
    dialog.setText(str(message))
    dialog.setStandardButtons(QMessageBox.Ok)
    dialog.button(QMessageBox.Ok).setText('Entendi')
    dialog.button(QMessageBox.Ok).setMinimumWidth(100)
    dialog.setDefaultButton(QMessageBox.Ok)
    dialog.exec()


class DataChangedError(ValueError):
    pass


def env_first(*names, default=""):
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def winthor_launch_args():
    """WinThor routine 529 action: EXE USUARIOWT SENHABD ALIASBD USUARIOBD CODROTINA."""
    if len(sys.argv) == 1:
        return None
    if len(sys.argv) != 6:
        raise ValueError('Parâmetros WinThor incompletos: esperados USUARIOWT SENHABD ALIASBD USUARIOBD CODROTINA.')
    usuario_wt, senha_bd, alias_bd, usuario_bd, codrotina = sys.argv[1:6]
    if not all((usuario_wt, senha_bd, alias_bd, usuario_bd, codrotina)):
        raise ValueError('O WinThor enviou um ou mais parâmetros vazios.')
    return {'usuario_wt': usuario_wt, 'senha_bd': senha_bd,
            'alias_bd': alias_bd, 'usuario_bd': usuario_bd, 'codrotina': codrotina}


def find_tns_directory(alias):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", alias):
        return None

    candidates = []
    seen = set()

    def add(directory):
        if not directory:
            return
        try:
            path = Path(os.path.expandvars(str(directory).strip('" ')))
            key = str(path).casefold()
            if key not in seen:
                seen.add(key)
                candidates.append(path)
        except (OSError, ValueError):
            return

    add(env_first("ORACLE_CONFIG_DIR", "TNS_ADMIN"))
    bundle_dir = Path(getattr(sys, "_MEIPASS", BASE_DIR))
    add(bundle_dir / "oracle_client" / "network" / "admin")
    add(BASE_DIR / "oracle_client" / "network" / "admin")
    oracle_home = os.getenv("ORACLE_HOME", "").strip()
    if oracle_home:
        add(Path(oracle_home) / "network" / "admin")

    if os.name == "nt":
        try:
            import winreg
        except ImportError:
            winreg = None
        if winreg is not None:
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for base in (r"SOFTWARE\ORACLE", r"SOFTWARE\WOW6432Node\ORACLE"):
                    try:
                        with winreg.OpenKey(root, base) as key:
                            subkeys = [""]
                            index = 0
                            while True:
                                try:
                                    subkeys.append(winreg.EnumKey(key, index))
                                    index += 1
                                except OSError:
                                    break
                        for subkey in subkeys:
                            path = base + ("\\" + subkey if subkey else "")
                            try:
                                with winreg.OpenKey(root, path) as key:
                                    try:
                                        add(winreg.QueryValueEx(key, "TNS_ADMIN")[0])
                                    except OSError:
                                        pass
                                    try:
                                        home = winreg.QueryValueEx(key, "ORACLE_HOME")[0]
                                        add(Path(home) / "network" / "admin")
                                    except OSError:
                                        pass
                            except OSError:
                                pass
                    except OSError:
                        pass

    for entry in os.getenv("PATH", "").split(os.pathsep):
        if "oracle" in entry.lower() or "client" in entry.lower():
            path = Path(entry.strip('" '))
            add(path / "network" / "admin")
            add(path.parent / "network" / "admin")

    pattern = re.compile(r"(?im)^\s*" + re.escape(alias) + r"\s*=")
    for folder in candidates:
        tnsnames = folder / "tnsnames.ora"
        try:
            if tnsnames.is_file() and pattern.search(
                    tnsnames.read_text(encoding="cp1252", errors="replace")):
                return folder
        except OSError:
            continue
    return None


def find_oracle_client_dir(configured=None):
    candidates = []
    seen = set()

    def add(directory):
        if not directory:
            return
        try:
            path = Path(os.path.expandvars(str(directory).strip('" '))).resolve()
            key = str(path).casefold()
            if key not in seen:
                seen.add(key)
                candidates.append(path)
        except (OSError, ValueError):
            return

    add(configured)
    add(Path(getattr(sys, "_MEIPASS", BASE_DIR)) / "oracle_client")
    add(BASE_DIR / "oracle_client")
    add(Path.cwd())

    oracle_home = os.getenv("ORACLE_HOME", "").strip()
    if oracle_home:
        add(oracle_home)
        add(Path(oracle_home) / "bin")

    for entry in os.getenv("PATH", "").split(os.pathsep):
        add(entry)

    if os.name == "nt":
        try:
            import winreg
        except ImportError:
            winreg = None
        if winreg is not None:
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for base in (r"SOFTWARE\ORACLE", r"SOFTWARE\WOW6432Node\ORACLE"):
                    try:
                        with winreg.OpenKey(root, base) as key:
                            subkeys = [""]
                            index = 0
                            while True:
                                try:
                                    subkeys.append(winreg.EnumKey(key, index))
                                    index += 1
                                except OSError:
                                    break
                        for subkey in subkeys:
                            registry_path = base + ("\\" + subkey if subkey else "")
                            try:
                                with winreg.OpenKey(root, registry_path) as key:
                                    try:
                                        home = winreg.QueryValueEx(key, "ORACLE_HOME")[0]
                                    except OSError:
                                        continue
                                    add(home)
                                    add(Path(home) / "bin")
                            except OSError:
                                pass
                    except OSError:
                        pass

    expected_machine = 0x8664 if struct.calcsize("P") == 8 else 0x14C
    for path in candidates:
        oci_dll = path / "oci.dll"
        try:
            with oci_dll.open("rb") as client_file:
                dos_header = client_file.read(64)
                if dos_header[:2] != b"MZ":
                    continue
                client_file.seek(int.from_bytes(dos_header[0x3C:0x40], "little"))
                pe_header = client_file.read(6)
            if pe_header[:4] == b"PE\0\0" and int.from_bytes(pe_header[4:6], "little") == expected_machine:
                return path
        except OSError:
            continue
    return None


def open_oracle_connection(winthor=None):
    # Compatível com o .env do projeto Gerenciador de Famílias.
    requested_mode = env_first("ORA_MODE", "ORACLE_MODE", default="auto").lower()
    if requested_mode not in ("auto", "thin", "thick"):
        raise ValueError("ORA_MODE deve ser auto, thin ou thick")
    user = winthor['usuario_bd'] if winthor else env_first("ORACLE_USER", "ORA_USER")
    password = winthor['senha_bd'] if winthor else env_first("ORACLE_PASSWORD", "ORA_PASSWORD")
    # Em execução WinThor, o alias recebido tem prioridade; .env define o modo e opcional TNS_ADMIN.
    dsn = winthor['alias_bd'] if winthor else env_first("ORACLE_DSN", "ORA_DSN")
    if not dsn:
        host = env_first("ORACLE_HOST", "ORA_HOST")
        port = env_first("ORACLE_PORT", "ORA_PORT", default="1521")
        service = env_first("ORACLE_SERVICE", "ORA_SERVICE")
        if host and service:
            dsn = f"{host}:{port}/{service}"
    if not (user and password and dsn):
        raise ValueError("Configure ORACLE_USER, ORACLE_PASSWORD e ORACLE_DSN (ou HOST/PORT/SERVICE) no .env, ou inicie pelo WinThor com os parâmetros corretos.")
    configured = env_first("ORACLE_CLIENT_LIB_DIR", "ORA_CLIENT_LIB_DIR")
    config_dir = env_first("ORACLE_CONFIG_DIR", "TNS_ADMIN")
    config_path = Path(config_dir).resolve() if config_dir else None
    if config_path is None:
        config_path = find_tns_directory(dsn)

    lib_dir = find_oracle_client_dir(configured)
    if winthor:
        if lib_dir is None:
            raise FileNotFoundError(
                "Oracle Client compatível com a arquitetura do programa não encontrado. "
                "Inclua o Oracle Client x64 na pasta oracle_client ao compilar."
            )
        kwargs = {"lib_dir": str(lib_dir)}
        if config_path:
            kwargs["config_dir"] = str(config_path)
        oracledb.init_oracle_client(**kwargs)
        mode = "thick"
    elif requested_mode == "thick":
        if lib_dir is None:
            raise FileNotFoundError(
                "Oracle Client não encontrado. Verifique ORACLE_HOME, PATH ou "
                "ORACLE_CLIENT_LIB_DIR; a pasta deve conter oci.dll."
            )
        kwargs = {"lib_dir": str(lib_dir)}
        if config_path:
            kwargs["config_dir"] = str(config_path)
        oracledb.init_oracle_client(**kwargs)
        mode = "thick"
    elif requested_mode == "auto":
        kwargs = {}
        if lib_dir is not None:
            kwargs["lib_dir"] = str(lib_dir)
        if config_path:
            kwargs["config_dir"] = str(config_path)
        try:
            oracledb.init_oracle_client(**kwargs)
        except oracledb.DatabaseError as error:
            if "DPI-1047" not in str(error):
                raise
            mode = "thin"
        else:
            mode = "thick"
    else:
        mode = "thin"

    if mode == "thin" and re.fullmatch(r"[A-Za-z0-9_.-]+", dsn) and config_path is None:
        raise FileNotFoundError(
            f"Não foi encontrado um tnsnames.ora com o alias {dsn}. "
            "Configure TNS_ADMIN ou verifique a configuração Oracle deste computador."
        )

    connect_kwargs = {"user": user, "password": password, "dsn": dsn, "program": "RB1601"}
    if mode == "thin" and config_path:
        connect_kwargs["config_dir"] = str(config_path)
    conn = oracledb.connect(**connect_kwargs)
    conn.autocommit = False
    return conn, mode

FIELDS = ['CODPRODMASTER','CODFILIAL','CODPROD','METODO','QT','NUMSEQ','PERCPERDA',
 'DTCADASTRO','CODFUNCCADASTRO','DTULTALTER','CODFUNCALTER','LOTEPRODUCAOMASTER',
 'CODFUNCULTALTER','FRACAOUMIDA','FRACAOSEPARACAO','VALIDADE','UNESTRUTURA',
 'ACEITAREQACIMAPREV','NUMETAPA','NUMDECIMAIS','NUMDECIMAL','PERCFORMULACAOTOTAL',
 'REPROCESSO','MODOPREPARO','METODOPADRAO','OBSMETODOTEMPS','OBSMETODO','VLPERDA','TEMPODECICLO']
# Preserve formulation fields, reset original auditing information to avoid attributing edits to other users.
COPY_FIELDS=[x for x in FIELDS if x not in ('CODPRODMASTER','CODFILIAL','METODO','DTCADASTRO',
 'CODFUNCCADASTRO','DTULTALTER','CODFUNCALTER','CODFUNCULTALTER')]

def as_text(v):
    return '' if v is None else str(v)

def key(row):
    # Actual uniqueness enforcement in TRG_CHAVE_PCCOMPOSICAO depends on NUMETAPA.
    if row.get('NUMETAPA') is not None and row['NUMETAPA'] > 0:
        return ('ETAPA',row['CODPROD'],row['NUMETAPA'])
    return ('FRACAO',row['CODPROD'],row['FRACAOUMIDA'])

def physical_key(row):
    # Physical PK (may be enabled in some installations).
    return (row['CODPROD'],row['FRACAOUMIDA'])


class WatermarkTable(QTableWidget):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.watermark=QPixmap(str(ASSETS_DIR / 'Logo tecnológico RBTech Soluções.png'))

    def paintEvent(self,event):
        super().paintEvent(event)
        if self.watermark.isNull():return
        area=self.viewport().rect()
        size=self.watermark.size().scaled(int(area.width()*.88),int(area.height()*.80),Qt.KeepAspectRatio)
        if size.isEmpty():return
        painter=QPainter(self.viewport())
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setCompositionMode(QPainter.CompositionMode_Multiply)
        painter.setOpacity(.075)
        painter.drawPixmap((area.width()-size.width())//2,(area.height()-size.height())//2,
                           size.width(),size.height(),self.watermark)
        painter.end()


class BlueIndicatorStyle(QProxyStyle):
    def drawPrimitive(self,element,option,painter,widget=None):
        if element not in (QStyle.PE_IndicatorRadioButton,QStyle.PE_IndicatorItemViewItemCheck):
            return super().drawPrimitive(element,option,painter,widget)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect=option.rect.adjusted(1,1,-1,-1)
        checked=bool(option.state & QStyle.State_On)
        painter.setPen(QPen(QColor('#004b80' if checked else '#526779'),1.5))
        painter.setBrush(QColor('#0066aa' if checked else '#ffffff'))
        if element==QStyle.PE_IndicatorRadioButton:painter.drawEllipse(rect)
        else:painter.drawRoundedRect(rect,2,2)
        if checked:
            path=QPainterPath()
            path.moveTo(rect.left()+rect.width()*.22,rect.top()+rect.height()*.52)
            path.lineTo(rect.left()+rect.width()*.43,rect.top()+rect.height()*.73)
            path.lineTo(rect.left()+rect.width()*.79,rect.top()+rect.height()*.29)
            painter.setPen(QPen(QColor('white'),2,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
            painter.drawPath(path)
        painter.restore()


class ProductLineEdit(QLineEdit):
    def keyPressEvent(self,event):
        if self.validator():
            if event.matches(QKeySequence.Paste):
                pasted=QApplication.clipboard().text()
                if not (pasted.isascii() and pasted.isdigit()):return
            elif event.text().isprintable() and event.text() and not event.modifiers() & (Qt.ControlModifier|Qt.AltModifier):
                if not (event.text().isascii() and event.text().isdigit()):return
        if self.validator() and ' - ' in self.text():
            replacing=(event.text().isascii() and event.text().isdigit()) or event.key() in (Qt.Key_Backspace,Qt.Key_Delete)
            if event.matches(QKeySequence.Paste):
                replacing=QApplication.clipboard().text().isascii() and QApplication.clipboard().text().isdigit()
            if replacing:
                self.clear()
                self.textEdited.emit('')
        super().keyPressEvent(event)


class SearchField(QWidget):
    """Código exato ou descrição parcial, com seleção explícita e nome no campo."""
    changed = Signal()
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.code = None
        self.description = ''
        self.conn = None
        self.search_timer=QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(350)
        self.search_timer.timeout.connect(lambda:self.lookup(auto=True))
        self.mode = QComboBox()
        self.mode.addItems(['Código', 'Descrição'])
        self.mode.setFixedWidth(78)
        self.edit = ProductLineEdit()
        self.code_validator=QRegularExpressionValidator(QRegularExpression('[0-9]*'),self.edit)
        self.edit.setValidator(self.code_validator)
        self.result_rows={}
        self.result_model=QStringListModel(self)
        self.completer=QCompleter(self.result_model,self)
        self.completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self.completer.popup().setStyleSheet('QListView { background:white; color:#18242c; selection-background-color:#cce5f7; selection-color:#12344c; }')
        self.completer.activated[str].connect(self.select_result)
        self.edit.setPlaceholderText('Código + Enter')
        self.edit.setMinimumWidth(60)
        self.edit.returnPressed.connect(self.lookup)
        self.edit.textEdited.connect(self.reset)
        self.mode.currentTextChanged.connect(self.change_mode)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(3)
        top = QHBoxLayout()
        if title:top.addWidget(QLabel(title))
        top.setSpacing(4)
        top.addWidget(self.mode)
        top.addWidget(self.edit, 1)
        layout.addLayout(top)
    def reset(self, *_):
        self.code = None
        self.description = ''
        self.result_rows.clear()
        self.result_model.setStringList([])
        self.edit.setToolTip('')
        self.changed.emit()
        self.search_timer.start()
    def change_mode(self, mode):
        self.edit.clear()
        self.edit.setValidator(self.code_validator if mode=='Código' else None)
        self.edit.setCompleter(self.completer if mode!='Código' else None)
        self.edit.setPlaceholderText('Código + Enter' if mode=='Código' else 'Nome ou %nome + Enter')
        self.reset()
    def set_product(self, code, desc):
        self.search_timer.stop()
        self.code = int(code)
        self.description = str(desc)
        self.completer.popup().hide()
        self.edit.setText(f'{code} - {desc}')
        self.edit.setToolTip(f'{code} - {desc}')
        self.edit.setCursorPosition(0)
        self.changed.emit()
    def select_result(self, text):
        row=self.result_rows.get(text)
        if row:self.set_product(*row)
    def lookup(self,auto=False):
        self.search_timer.stop()
        if self.code is not None:return
        if not self.conn:
            if auto:return
            show_alert(self,'Pesquisa','A conexão Oracle não está disponível.')
            return
        term = self.edit.text().strip()
        if not term:
            return
        try:
            with self.conn.cursor() as cur:
                if self.mode.currentText()=='Código':
                    if not term.isdecimal():
                        raise ValueError('Informe um CODPROD numérico.')
                    cur.execute('SELECT CODPROD, DESCRICAO FROM PCPRODUT WHERE CODPROD=:p AND DTEXCLUSAO IS NULL',p=int(term))
                    row=cur.fetchone()
                    if not row: raise ValueError('Não encontramos um produto com esse código. Confira o número ou pesquise pela descrição.')
                    self.set_product(*row)
                    return
                cur.execute('''SELECT CODPROD, DESCRICAO FROM (
                    SELECT CODPROD, DESCRICAO FROM PCPRODUT
                    WHERE DTEXCLUSAO IS NULL AND UPPER(DESCRICAO) LIKE :q
                    ORDER BY CASE WHEN ENVIARFORCAVENDAS = 'S' THEN 0 ELSE 1 END,
                             CASE WHEN CODMARCA IS NOT NULL THEN 0 ELSE 1 END,
                             CODPROD) WHERE ROWNUM <= 200''',q=term.upper()+'%')
                rows=cur.fetchall()
            if not rows: raise ValueError('Não encontramos produtos com esse nome. Tente um nome mais curto ou use % no início para buscar em qualquer parte da descrição.')
            self.result_rows={f'{code} - {desc}':(code,desc) for code,desc in rows}
            self.result_model.setStringList(list(self.result_rows))
            self.completer.setCompletionPrefix('')
            self.completer.complete()
        except Exception as exc:
            if auto:self.edit.setToolTip(str(exc))
            else:show_alert(self,'Pesquisa',str(exc))


def make_item(value, color=None):
    item=QTableWidgetItem('' if value is None else str(value))
    item.setFlags(item.flags() & ~(Qt.ItemIsEditable | Qt.ItemIsUserCheckable))
    if color:
        from PySide6.QtGui import QColor
        item.setBackground(QColor(color))
    return item


def fmt_qty(value):
    if value is None:return ''
    return format(Decimal(str(value)),',f').replace(',','_').replace('.',',').replace('_','.')


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        if not isinstance(QApplication.instance().style(),BlueIndicatorStyle):
            QApplication.instance().setStyle(BlueIndicatorStyle('Fusion'))
        QApplication.instance().setStyleSheet(ALERT_STYLES)
        app_icon=QIcon(str(APP_ICON_PATH))
        QApplication.instance().setWindowIcon(app_icon)
        self.setWindowIcon(app_icon)
        self.setWindowTitle('Clonar Estrutura de Produto')
        self.resize(1200,570)
        self.setMinimumSize(970,460)
        self.conn=None
        self.source=[]
        self.target=[]
        self.plan=None
        self.snapshot=None
        self.origin_loaded=False
        self.source_snapshot=None
        self.operation_completed=False
        self.connection_uncertain=False
        self.winthor=None
        self.startup_error=None
        try: self.winthor=winthor_launch_args()
        except Exception as exc:self.startup_error=str(exc)
        root=QWidget()
        self.setCentralWidget(root)
        layout=QVBoxLayout(root)
        layout.setContentsMargins(7,5,7,4)
        layout.setSpacing(5)
        split=QSplitter(Qt.Horizontal)
        layout.addWidget(split,1)
        self.origin_group=QGroupBox('Produto ORIGEM')
        self.dest_group=QGroupBox('Produto DESTINO')
        split.addWidget(self.origin_group)
        split.addWidget(self.dest_group)
        split.setSizes([600,600])
        self.origin=SearchField('')
        self.dest=SearchField('')
        self.origin.changed.connect(self.invalidate_origin)
        self.dest.changed.connect(self.invalidate_dest)
        self.origin_method=QComboBox()
        self.origin_method.setMinimumWidth(55)
        self.origin_method.setToolTip('Método da origem: o primeiro disponível é selecionado na consulta.')
        self.origin_method.currentIndexChanged.connect(self.change_origin_method)
        self.method=QComboBox()
        self.method.setEditable(True)
        self.method.setToolTip('Selecione um método existente ou digite um novo. A formulação será criada ao confirmar a cópia.')
        self.method.addItem('1')
        self.method.setFixedWidth(55)
        self.dest_timer=QTimer(self)
        self.dest_timer.setSingleShot(True)
        self.dest_timer.setInterval(300)
        self.dest_timer.timeout.connect(self.load_destination)
        self.method.currentTextChanged.connect(self.schedule_destination)
        self.origin_branch=QComboBox()
        self.dest_branch=QComboBox()
        for branch in (self.origin_branch,self.dest_branch):
            branch.setFixedWidth(55)
            branch.setEnabled(False)
        self.origin_branch.currentIndexChanged.connect(self.invalidate_origin)
        self.dest_branch.currentIndexChanged.connect(self.invalidate_dest)
        self.source_table=self.create_table(['✓','Código','Matéria-prima / Componente','Un','Qtde','Fração','Etapa','Mét.'])
        self.target_table=self.create_table(['Código','Matéria-prima / Componente','Un','Qtde','Fração','Etapa'])
        self.source_table.itemChanged.connect(self.on_table_change)
        for group,field,table,is_origin in [(self.origin_group,self.origin,self.source_table,True),(self.dest_group,self.dest,self.target_table,False)]:
            lay=QVBoxLayout(group)
            lay.setContentsMargins(6,7,6,6)
            lay.setSpacing(5)
            top=QHBoxLayout()
            top.setSpacing(4)
            top.addWidget(field,1)
            top.addWidget(QLabel('Filial'))
            top.addWidget(self.origin_branch if is_origin else self.dest_branch)
            top.addWidget(QLabel('Método'))
            top.addWidget(self.origin_method if is_origin else self.method)
            lay.addLayout(top)
            lay.addWidget(table,1)
            if is_origin:
                table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch)
                for column,width in ((0,44),(1,64),(3,37),(4,67),(5,54),(6,102),(7,42)):
                    table.setColumnWidth(column,width)
                table.horizontalHeader().setSectionResizeMode(4,QHeaderView.ResizeToContents)
            else:
                table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
                for column,width in ((0,64),(2,37),(3,67),(4,54),(5,102)):
                    table.setColumnWidth(column,width)
                table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeToContents)
        bottom=QHBoxLayout()
        layout.addLayout(bottom)
        summary=QGroupBox('Resumo da comparação')
        summary_layout=QVBoxLayout(summary)
        summary_layout.setContentsMargins(8,5,8,5)
        self.summary=QLabel('Selecione os produtos para comparar automaticamente.')
        summary_layout.addWidget(self.summary)
        self.summary.setWordWrap(True)
        bottom.addWidget(summary,3)
        legend=QGroupBox('Legenda')
        legend_layout=QVBoxLayout(legend)
        legend_layout.setContentsMargins(8,5,8,5)
        legend_text=QLabel('Pesquisa: Código = exato; Descrição = início do nome.\n'
                          '%nome = qualquer parte. Busca automática ao digitar.\n'
                          '☑ Marque na origem somente os componentes a copiar.\n'
                          'A estrutura final do destino ficará igual à seleção.')
        legend_text.setWordWrap(True)
        legend_layout.addWidget(legend_text)
        bottom.addWidget(legend,4)
        footer=QHBoxLayout()
        layout.addLayout(footer)
        self.connection_status=QLabel('Conectando...')
        footer.addWidget(self.connection_status,1)
        self.confirm=QPushButton('Confirmar')
        self.confirm.setFixedWidth(115)
        self.confirm.setEnabled(False)
        self.confirm.clicked.connect(self.confirm_changes)
        footer.addWidget(self.confirm)
        self.statusBar().showMessage('Conectando automaticamente ao Oracle...')
        self.setStyleSheet('''
            QMainWindow { background:#edf0f3; }
            QGroupBox { border:1px solid #aab6c2; margin-top:9px; padding-top:5px; font-weight:bold; color:#00538a; }
            QGroupBox::title { subcontrol-origin:margin; left:9px; padding:0 4px; }
            QTableWidget { background:white; alternate-background-color:#f0f6fc; color:#17232e; gridline-color:#d8dee5; font-weight:normal; selection-background-color:#cce5f7; selection-color:#12344c; }
            QTableWidget::item:selected { background:#cce5f7; color:#12344c; }
            QStatusBar { background:#edf0f3; color:#17232e; }
            QHeaderView::section { background:#dce3e9; color:#26323b; padding:3px; border:1px solid #b8c2ca; }
            QLineEdit,QComboBox { background:white; color:#18242c; padding:2px; border:1px solid #aab5bf; selection-background-color:#cce5f7; selection-color:#12344c; }
            QComboBox QAbstractItemView { background:white; color:#18242c; selection-background-color:#cce5f7; selection-color:#12344c; border:1px solid #aab5bf; outline:0; }
            QComboBox QAbstractItemView::item { min-height:22px; padding:2px 5px; }
            QComboBox QAbstractItemView::item:selected { background:#cce5f7; color:#12344c; }
            QPushButton { background:#e3e9ee; color:#142b3b; padding:4px 9px; border:1px solid #aab5bf; }
            QPushButton:disabled { color:#8a9199; }
            QPushButton#primary { background:#005a97; color:white; font-weight:bold; }
            QLabel { color:#17232e; font-weight:normal; }
        '''+ALERT_STYLES)
        self.confirm.setObjectName('primary')
        QTimer.singleShot(0,self.connect_db)

    def create_table(self,headers):
        table=WatermarkTable(0,len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().hide()
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(False)
        return table

    def invalidate_plan(self,*_):
        self.plan=None
        same_destination=self.same_product_branch() and (self.method.currentText().strip()==self.origin_method.currentText().strip() or bool(self.target))
        self.confirm.setEnabled(self.origin_loaded and self.snapshot is not None and bool(self.source or self.target) and not same_destination and not self.operation_completed and not self.connection_uncertain)
        self.refresh_summary()

    def same_product_branch(self):
        return self.origin.code==self.dest.code and self.origin_branch.currentData()==self.dest_branch.currentData()

    def update_comparison(self,source_checks=None):
        if source_checks is None:
            source_checks=[self.source_table.item(i,0).checkState() for i in range(self.source_table.rowCount())]
            if len(source_checks)!=len(self.source):source_checks=None
        self.populate(source_checks)
        self.statusBar().showMessage(f'Origem: {len(self.source)} componentes | Destino: {len(self.target)} componentes')

    def invalidate_comparison(self,*_):
        self.target=[]
        self.snapshot=None
        self.target_table.setRowCount(0)
        self.update_comparison()

    def invalidate_origin(self,*_):
        self.operation_completed=False
        self.origin_loaded=False
        self.source=[]
        self.source_table.setRowCount(0)
        with QSignalBlocker(self.origin_method):
            self.origin_method.clear()
        try:
            if self.conn and self.origin.code and self.origin_branch.currentData() is not None:
                with self.conn.cursor() as cur:
                    cur.execute('SELECT DISTINCT METODO FROM PCCOMPOSICAO WHERE CODPRODMASTER=:p AND CODFILIAL=:f ORDER BY METODO',
                        p=self.origin.code,f=self.origin_branch.currentData())
                    methods=[row[0] for row in cur if row[0] is not None]
                with QSignalBlocker(self.origin_method):
                    for method in methods:self.origin_method.addItem(str(method),method)
            self.load_origin()
        except Exception as exc:
            self.update_comparison()
            show_alert(self,'Origem',str(exc))

    def change_origin_method(self,*_):
        self.load_origin()

    def load_origin(self):
        self.operation_completed=False
        self.origin_loaded=False
        self.source_snapshot=None
        self.source=[]
        self.source_table.setRowCount(0)
        try:
            if self.conn and self.origin.code and self.origin_branch.currentData() is not None and self.origin_method.currentIndex()>=0:
                self.source=self.fetch(self.origin.code,self.origin_branch.currentData(),self.origin_method.currentData())
                self.source_snapshot=self.fingerprint(self.source)
                self.origin_loaded=True
        except Exception as exc:
            show_alert(self,'Origem',str(exc))
        self.update_comparison()

    def schedule_destination(self,*_):
        self.operation_completed=False
        self.invalidate_comparison()
        self.dest_timer.start()

    def invalidate_dest(self,*_):
        self.operation_completed=False
        self.dest_timer.stop()
        self.invalidate_comparison()
        try:
            with QSignalBlocker(self.method):
                self.method.clear()
                if self.conn and self.dest.code and self.dest_branch.currentData() is not None:
                    with self.conn.cursor() as cur:
                        cur.execute('SELECT DISTINCT METODO FROM PCCOMPOSICAO WHERE CODPRODMASTER=:p AND CODFILIAL=:f ORDER BY METODO',
                            p=self.dest.code,f=self.dest_branch.currentData())
                        for row in cur:
                            if row[0] is not None:self.method.addItem(str(row[0]),row[0])
                if self.method.count()==0:self.method.addItem('1')
            self.load_destination()
        except Exception as exc:
            show_alert(self,'Destino',str(exc))

    def load_destination(self):
        self.dest_timer.stop()
        self.target=[]
        self.snapshot=None
        self.target_table.setRowCount(0)
        try:
            method=self.method.currentText().strip()
            if self.conn and self.dest.code and self.dest_branch.currentData() is not None and method:
                self.target=self.fetch(self.dest.code,self.dest_branch.currentData(),method)
                self.snapshot=self.fingerprint(self.target)
        except Exception as exc:
            show_alert(self,'Destino',str(exc))
        self.update_comparison()

    def connect_db(self):
        try:
            if self.startup_error:raise ValueError(self.startup_error)
            self.conn,mode=open_oracle_connection(self.winthor)
            self.origin.conn=self.conn
            self.dest.conn=self.conn
            branches=self.available_branches()
            if not branches:raise ValueError('Nenhuma filial cadastrada.')
            for field in (self.origin_branch,self.dest_branch):
                with QSignalBlocker(field):
                    field.clear()
                    for code in branches:field.addItem(code,code)
                    if '1' in branches:field.setCurrentIndex(branches.index('1'))
                field.setEnabled(True)
            self.invalidate_origin()
            self.invalidate_dest()
            auth=f'WinThor: {self.winthor["usuario_wt"]}' if self.winthor else '.env'
            self.connection_status.setText(f'Conectado: {auth} | {mode.upper()}')
            self.statusBar().showMessage('Pronto. Informe origem e destino.')
        except Exception as exc:
            self.connection_status.setText('Sem conexão')
            show_error(self,'Conexão Oracle',str(exc))

    def closeEvent(self,event):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception as exc:
                show_error(self,'Encerramento da conexão Oracle',str(exc))
                event.ignore()
                return
        event.accept()

    def available_branches(self):
        with self.conn.cursor() as cur:
            cur.execute('SELECT CODIGO FROM PCFILIAL ORDER BY CODIGO')
            return list(dict.fromkeys(code for row in cur
                if (code:=str(row[0]).strip()) and code.lstrip('0')!='99'))

    def fetch(self,product,branch,method=None):
        sql='''SELECT C.*, P.DESCRICAO AS DESC_COMPONENTE, P.UNIDADE AS UN_COMPONENTE,
          E.DESCRICAO AS DESC_ETAPA FROM PCCOMPOSICAO C
          LEFT JOIN PCPRODUT P ON P.CODPROD=C.CODPROD
          LEFT JOIN PCETAPAPRODUCAO E ON E.CODETAPA=C.NUMETAPA
          WHERE C.CODPRODMASTER=:p AND C.CODFILIAL=:f'''
        args={'p':int(product),'f':branch}
        if method is not None:
            sql+=' AND C.METODO=:m';args['m']=method
        sql+=' ORDER BY C.METODO,C.NUMSEQ,C.CODPROD'
        with self.conn.cursor() as cur:
            cur.execute(sql,args)
            names=[d[0] for d in cur.description]
            rows=[]
            for vals in cur:
                row=dict(zip(names,vals))
                if hasattr(row.get('OBSMETODO'),'read'):
                    row['OBSMETODO']=row['OBSMETODO'].read()
                rows.append(row)
            return rows

    def collision(self,a,b):
        return key(a)==key(b) or physical_key(a)==physical_key(b)

    def populate(self,selections=None):
        source_blocker=QSignalBlocker(self.source_table)
        self.source_table.setRowCount(len(self.source))
        self.target_table.setRowCount(len(self.target))
        for i,r in enumerate(self.source):
            cand=dict(r);cand['METODO']=self.method.currentText().strip()
            conflict=any(self.collision(cand,t) for t in self.target)
            color='#fff0b9' if conflict else None
            check=QTableWidgetItem('')
            check.setFlags(Qt.ItemIsEnabled|Qt.ItemIsUserCheckable|Qt.ItemIsSelectable)
            check.setCheckState(selections[i] if selections is not None else Qt.Checked)
            if color:
                from PySide6.QtGui import QColor
                check.setBackground(QColor(color))
            self.source_table.setItem(i,0,check)
            etapa=(f'{r["NUMETAPA"]} - {r["DESC_ETAPA"]}' if r.get('NUMETAPA') and r.get('DESC_ETAPA') else r.get('NUMETAPA'))
            vals=[r['CODPROD'],r.get('DESC_COMPONENTE'),r.get('UNESTRUTURA') or r.get('UN_COMPONENTE'),fmt_qty(r.get('QT')),r.get('FRACAOUMIDA'),etapa,r.get('METODO')]
            for j,val in enumerate(vals,1):self.source_table.setItem(i,j,make_item(val,color))
        for i,r in enumerate(self.target):
            conflict=any(self.collision(dict(s,METODO=self.method.currentText().strip()),r) for s in self.source)
            color='#fff0b9' if conflict else None
            etapa=(f'{r["NUMETAPA"]} - {r["DESC_ETAPA"]}' if r.get('NUMETAPA') and r.get('DESC_ETAPA') else r.get('NUMETAPA'))
            vals=[r['CODPROD'],r.get('DESC_COMPONENTE'),r.get('UNESTRUTURA') or r.get('UN_COMPONENTE'),fmt_qty(r.get('QT')),r.get('FRACAOUMIDA'),etapa]
            for j,val in enumerate(vals):self.target_table.setItem(i,j,make_item(val,color))
        self.invalidate_plan()

    def on_table_change(self,item):
        self.operation_completed=False
        self.invalidate_plan()

    def refresh_summary(self):
        if not hasattr(self,'summary'):return
        selected=[self.source[i] for i in range(min(len(self.source),self.source_table.rowCount()))
                  if self.source_table.item(i,0).checkState()==Qt.Checked]
        selected_rows=[dict(row,METODO=self.method.currentText().strip()) for row in selected]
        to_update=sum(
            any(self.collision(row,target) for target in self.target)
            for row in selected_rows
        )
        to_remove=max(0,len(self.target)-to_update)
        to_insert=max(0,len(selected_rows)-to_update)
        self.summary.setText(
            f'Selecionados na origem: {len(selected)}\n'
            f'Componentes existentes a atualizar: {to_update}\n'
            f'Componentes excedentes a remover: {to_remove}\n'
            f'Componentes novos a inserir: {to_insert}'
        )

    def fingerprint(self,rows):
        # Snapshot de todos os campos técnicos usados na cópia, incluindo QT.
        return Counter(tuple(str(r.get(c)) for c in FIELDS) for r in rows)

    def build_plan(self,target=None):
        if self.connection_uncertain:raise ValueError('A conexão foi interrompida. Reinicie a rotina e confira os dados no banco antes de tentar novamente.')
        if self.operation_completed:raise ValueError('Esta operação já foi concluída. Selecione os componentes para iniciar uma nova cópia.')
        if not self.origin_loaded or self.snapshot is None:raise ValueError('Aguarde a consulta da origem e do destino antes de confirmar.')
        if self.same_product_branch() and (self.method.currentText().strip()==self.origin_method.currentText().strip() or self.target):
            raise ValueError('Para copiar o mesmo produto na mesma filial, informe um método novo no destino.')
        if target is None:target=self.target
        removals=set(range(len(target)))
        updates=[]
        inserts=[]
        selected=[dict(self.source[i],METODO=self.method.currentText().strip()) for i in range(len(self.source)) if self.source_table.item(i,0).checkState()==Qt.Checked]
        # Componentes da origem consolidados no mesmo método devem ser únicos.
        for i,a in enumerate(selected):
            for b in selected[:i]:
                if self.collision(a,b):
                    raise ValueError(f'O componente {a["CODPROD"]} se repete entre métodos da origem. Desmarque uma das linhas.')
        for cand in selected:
            if int(cand['CODPROD'])==self.dest.code:
                raise ValueError(f'O produto destino {self.dest.code} está selecionado como componente. Desmarque esse item na origem: um produto não pode fazer parte da própria composição.')
            logical_matches=[j for j,t in enumerate(target)
                             if j in removals and key(cand)==key(t)]
            physical_matches=[j for j,t in enumerate(target)
                              if j in removals and physical_key(cand)==physical_key(t)]
            matches=logical_matches or physical_matches
            if len(matches)>1:
                raise ValueError(
                    f'Foram encontrados vários vínculos no destino para o componente '
                    f'{cand["CODPROD"]}. Revise a estrutura antes de substituir.'
                )
            if matches:
                index=matches[0]
                removals.remove(index)
                updates.append({'index':index,'row':cand})
            else:
                inserts.append(cand)
        return {'inserts':inserts,'updates':updates,'removals':sorted(removals)}

    def confirm_changes(self):
        try:
            self.origin.search_timer.stop()
            self.dest.search_timer.stop()
            if self.dest_timer.isActive():self.load_destination()
            self.build_plan()
            operation={
                'product':self.dest.code,'method':self.method.currentText().strip(),
                'source_product':self.origin.code,'source_branch':self.origin_branch.currentData(),
                'source_method':self.origin_method.currentData(),'source_snapshot':self.source_snapshot,
            }
            chosen=self.dest_branch.currentData()
            branches=[chosen]
            if any(self.source_table.item(i,0).checkState()==Qt.Checked for i in range(len(self.source))):
                scope=QMessageBox(self)
                scope.setWindowTitle('Filiais da cópia')
                scope.setText('Deseja copiar a estrutura selecionada\npara todas as filiais?')
                scope.setInformativeText(
                    f'Escolha todas as filiais ou somente a filial\n{chosen}, selecionada no destino.'
                )
                only=scope.addButton(f'Somente filial {chosen}',QMessageBox.AcceptRole)
                all_branches=scope.addButton('Todas as filiais',QMessageBox.ActionRole)
                cancel=scope.addButton(QMessageBox.Cancel)
                cancel.setText('Cancelar')
                only.setMinimumWidth(180)
                all_branches.setMinimumWidth(160)
                cancel.setMinimumWidth(110)
                scope.setDefaultButton(only)
                scope.exec()
                if scope.clickedButton()==all_branches:
                    branches=self.available_branches()
                    if not branches:raise ValueError('Nenhuma filial cadastrada.')
                    if chosen not in branches:raise ValueError('Filial de destino não encontrada no cadastro de filiais.')
                    if self.origin.code==self.dest.code and self.method.currentText().strip()==self.origin_method.currentText().strip():
                        branches=[f for f in branches if int(f)!=int(self.origin_branch.currentData())]
                elif scope.clickedButton()!=only:
                    return
            batches=[]
            for branch in branches:
                target=self.target if branch==chosen else self.fetch(self.dest.code,branch,self.method.currentText().strip())
                if self.origin.code==self.dest.code and branch==self.origin_branch.currentData() and target:
                    raise ValueError('O método destino já existe na filial de origem. Para o mesmo produto e filial, escolha um método novo.')
                plan=self.build_plan() if branch==chosen else self.build_plan(target)
                batches.append({'branch':branch,'target':target,'snapshot':self.snapshot if branch==chosen else self.fingerprint(target),'plan':plan})
            if not any(b['plan']['inserts'] or b['plan']['updates'] or b['plan']['removals'] for b in batches):
                show_info(self,'Sem alterações','Nenhuma alteração a gravar.')
                return
            details=(f'Produto destino: {self.dest.code} | Método: {self.method.currentText()}\n'
                f'Filiais: {", ".join(branches)}\n'
                'O método de origem é preservado.\n\n'+
                '\n'.join(
                    f'Filial {b["branch"]}: atualizar {len(b["plan"]["updates"])} existentes, '
                    f'remover {len(b["plan"]["removals"])} excedentes e inserir '
                    f'{len(b["plan"]["inserts"])} novos'
                    for b in batches
                )+
                '\n\nA estrutura final ficará igual aos componentes marcados na origem.\n'
                'Vínculos com a mesma chave serão atualizados para respeitar a trigger Oracle.\n'
                'As alterações serão feitas no Oracle.\nDeseja continuar?')
            confirmation=QMessageBox(self)
            confirmation.setIcon(QMessageBox.Question)
            confirmation.setWindowTitle('Confirmar alterações')
            confirmation.setText(details)
            confirmation.setStandardButtons(QMessageBox.Yes|QMessageBox.No)
            yes=confirmation.button(QMessageBox.Yes)
            no=confirmation.button(QMessageBox.No)
            yes.setText('Sim')
            no.setText('Não')
            yes.setMinimumWidth(100)
            no.setMinimumWidth(100)
            confirmation.setMinimumWidth(640)
            confirmation.setDefaultButton(QMessageBox.No)
            if confirmation.exec()!=QMessageBox.Yes:return
            self.commit(batches,operation)
        except Exception as exc:
            show_alert(self,'Validação',str(exc))

    def commit(self,batches,operation):
        committed=False
        commit_attempted=False
        try:
            self.confirm.setEnabled(False)
            # Revalida e bloqueia a origem antes de modificar qualquer filial.
            with self.conn.cursor() as cur:
                cur.execute('''SELECT C.* FROM PCCOMPOSICAO C WHERE C.CODPRODMASTER=:p
                    AND C.CODFILIAL=:f AND C.METODO=:m FOR UPDATE''',
                    p=operation['source_product'],f=operation['source_branch'],m=operation['source_method'])
                current=self.cursor_rows(cur)
                if self.fingerprint(current)!=operation['source_snapshot']:
                    raise DataChangedError('Os dados pesquisados da origem foram alterados. Atualize a pesquisa e revise os componentes antes de concluir a transação.')
            for batch in batches:
                plan=batch['plan']
                # Bloqueia os registros existentes e valida se houve alteração desde a consulta.
                with self.conn.cursor() as cur:
                    cur.execute('''SELECT C.* FROM PCCOMPOSICAO C WHERE C.CODPRODMASTER=:p
                        AND C.CODFILIAL=:f AND C.METODO=:m FOR UPDATE''',
                        p=operation['product'],f=batch['branch'],m=operation['method'])
                    current=self.cursor_rows(cur)
                    if self.fingerprint(current)!=batch['snapshot']:
                        raise DataChangedError(f'Os dados pesquisados do destino na filial {batch["branch"]} foram alterados. Atualize a pesquisa e revise os componentes antes de concluir a transação.')
                    def row_where(row):
                        return {
                            'p':operation['product'],'f':batch['branch'],'m':operation['method'],
                            'c':row['CODPROD'],'fr':row.get('FRACAOUMIDA'),'et':row.get('NUMETAPA'),
                        }
                    row_condition='''CODPRODMASTER=:p AND CODFILIAL=:f AND METODO=:m AND CODPROD=:c
                        AND (FRACAOUMIDA=:fr OR (FRACAOUMIDA IS NULL AND :fr IS NULL))
                        AND (NUMETAPA=:et OR (NUMETAPA IS NULL AND :et IS NULL))'''
                    for index in plan['removals']:
                        cur.execute('DELETE FROM PCCOMPOSICAO WHERE '+row_condition,
                                    row_where(batch['target'][index]))
                        if cur.rowcount!=1:
                            raise ValueError('Não foi possível remover exatamente um componente excedente do destino.')
                    assignments=', '.join(f'{column}=:u{i}' for i,column in enumerate(COPY_FIELDS))
                    update_sql='UPDATE PCCOMPOSICAO SET '+assignments+' WHERE '+row_condition
                    for update in plan['updates']:
                        values={f'u{i}':update['row'].get(column)
                                for i,column in enumerate(COPY_FIELDS)}
                        values.update(row_where(batch['target'][update['index']]))
                        cur.execute(update_sql,values)
                        if cur.rowcount!=1:
                            raise ValueError('Não foi possível atualizar exatamente um vínculo correspondente no destino.')
                    cols=['CODPRODMASTER','CODFILIAL','METODO']+COPY_FIELDS
                    bindcols=[f':v{i}' for i in range(len(cols))]
                    sql=f'INSERT INTO PCCOMPOSICAO ({", ".join(cols)}, DTCADASTRO) VALUES ({", ".join(bindcols)}, SYSDATE)'
                    for row in plan['inserts']:
                        if int(row['CODPROD'])==operation['product']:
                            raise ValueError('Cópia bloqueada: o produto destino não pode ser componente dele mesmo. Desmarque o item na origem.')
                        values=[operation['product'],batch['branch'],operation['method']]+[row.get(c) for c in COPY_FIELDS]
                        cur.execute(sql,{f'v{i}':v for i,v in enumerate(values)})
            # Confere também inclusões na origem ocorridas durante a gravação.
            with self.conn.cursor() as cur:
                cur.execute('''SELECT C.* FROM PCCOMPOSICAO C WHERE C.CODPRODMASTER=:p
                    AND C.CODFILIAL=:f AND C.METODO=:m FOR UPDATE''',
                    p=operation['source_product'],f=operation['source_branch'],m=operation['source_method'])
                if self.fingerprint(self.cursor_rows(cur))!=operation['source_snapshot']:
                    raise DataChangedError('Os dados pesquisados da origem foram alterados durante a operação. Atualize a pesquisa antes de concluir a transação.')
            commit_attempted=True
            self.conn.commit()
            committed=True
            self.plan=None
            self.finish_operation()
            show_info(
                self,
                'Concluído',
                'Formulação atualizada com sucesso.\n'
                'Operação concluída.\n'
                'Para outra cópia, selecione novamente\n'
                'os componentes.',
            )
        except Exception as exc:
            if committed:
                self.operation_completed=True
                self.confirm.setEnabled(False)
                show_error(self,'Atualização da tela',f'A gravação foi concluída, mas não foi possível atualizar a tela. Não repita a operação sem conferir o banco. Detalhes: {exc}')
                return
            try:
                self.conn.rollback()
            except Exception as rollback_error:
                self.connection_uncertain=True
                self.confirm.setEnabled(False)
                show_error(self,'Conexão interrompida',f'Não foi possível confirmar o desfazimento da operação. Reinicie a rotina e confira os dados no banco antes de repetir.\n\nErro original: {exc}\nFalha ao desfazer: {rollback_error}')
                return
            if commit_attempted:
                self.connection_uncertain=True
                self.confirm.setEnabled(False)
                show_error(self,'Resultado da gravação não confirmado',f'Houve uma falha ao confirmar a gravação. Confira os dados no banco e reinicie a rotina antes de repetir: não foi possível determinar se a operação foi gravada.\n\nErro original: {exc}')
                return
            if isinstance(exc,DataChangedError):
                self.origin_loaded=False
                self.source_snapshot=None
                self.snapshot=None
                self.confirm.setEnabled(False)
                show_alert(self,'Pesquisa desatualizada',str(exc))
                # A atualização exige nova confirmação, sem reaplicar o plano antigo.
                self.load_origin()
                self.load_destination()
            else:
                self.invalidate_plan()
                show_error(self,'Operação cancelada (ROLLBACK)',str(exc))

    def cursor_rows(self,cur):
        names=[d[0] for d in cur.description]
        rows=[]
        for values in cur:
            row=dict(zip(names,values))
            if hasattr(row.get('OBSMETODO'),'read'):row['OBSMETODO']=row['OBSMETODO'].read()
            rows.append(row)
        return rows

    def finish_operation(self):
        self.operation_completed=True
        self.load_destination()
        with QSignalBlocker(self.source_table):
            for i in range(self.source_table.rowCount()):
                self.source_table.item(i,0).setCheckState(Qt.Unchecked)
        self.operation_completed=True
        self.invalidate_plan()
        self.statusBar().showMessage('Operação concluída. Selecione os componentes para iniciar uma nova cópia.')

if __name__=='__main__':
    app=QApplication(sys.argv)
    app.setStyle('Fusion')
    window=App()
    window.show()
    sys.exit(app.exec())
