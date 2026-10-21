"""RB Formulações 1601 - copiar composição WinThor com prévia e transação."""
import os
import sys
from collections import Counter
from pathlib import Path
from dotenv import load_dotenv
from decimal import Decimal, localcontext
from PySide6.QtCore import Qt, QTimer, Signal, QSignalBlocker, QRegularExpression, QStringListModel
from PySide6.QtGui import QRegularExpressionValidator, QKeySequence, QColor, QPen, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,
 QLineEdit,QPushButton,QLabel,QTableWidget,QTableWidgetItem,QMessageBox,QComboBox,QCheckBox,
 QSplitter,QHeaderView,QAbstractItemView,QInputDialog,QDialog,QDialogButtonBox,QGridLayout,QGroupBox,QRadioButton,QButtonGroup,QFrame,QSizePolicy,QCompleter,QProxyStyle,QStyle)
import oracledb

# Oracle NUMBER deve chegar como Decimal, antes de qualquer exibição ou cálculo.
oracledb.defaults.fetch_decimals = True

BASE_DIR = Path(getattr(sys, "executable", __file__)).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
ASSETS_DIR = Path(getattr(sys, '_MEIPASS', BASE_DIR)) / 'assets'

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
        dialog.setText('Não foi possível concluir a operação no banco de dados.')
        dialog.setInformativeText('Confira a conexão e tente novamente. Consulte os detalhes do erro abaixo.')
        dialog.setDetailedText(message)
    else:
        dialog.setText(message)
    if title=='Operação cancelada (ROLLBACK)':
        dialog.setInformativeText('As alterações desta operação foram desfeitas. Revise os dados antes de tentar novamente.')
    dialog.setStandardButtons(QMessageBox.Ok)
    dialog.button(QMessageBox.Ok).setText('Entendi')
    dialog.exec()


def show_error(parent,title,message):
    show_alert(parent,title,message,QMessageBox.Critical)


class DataChangedError(ValueError):
    pass


def exact_quantity_sum(left,right):
    left,right=Decimal(str(left)),Decimal(str(right))
    with localcontext() as context:
        context.prec=max(left.adjusted(),right.adjusted())-min(left.as_tuple().exponent,right.as_tuple().exponent)+3
        result=left+right
    significant=''.join(map(str,result.as_tuple().digits)).rstrip('0')
    if len(significant)>38:
        raise ValueError('A soma excede a precisão do Oracle. Revise as quantidades antes de continuar.')
    return result


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


def open_oracle_connection(winthor=None):
    # Compatível com o .env do projeto Gerenciador de Famílias.
    mode = env_first("ORA_MODE", "ORACLE_MODE", default="thick").lower()
    if mode not in ("thin", "thick"):
        raise ValueError("ORA_MODE deve ser thin ou thick")
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
    if mode == "thick":
        # Prioriza a mesma pasta oracle_client usada no Gerenciador de Famílias.
        configured = env_first("ORACLE_CLIENT_LIB_DIR", "ORA_CLIENT_LIB_DIR")
        lib_dir = Path(configured) if configured else BASE_DIR / "oracle_client"
        if not lib_dir.is_dir():
            raise FileNotFoundError(f"Oracle Client 19 não encontrado em: {lib_dir}. Copie o Instant Client 19 completo para oracle_client ou defina ORACLE_CLIENT_LIB_DIR no .env")
        config_dir = env_first("ORACLE_CONFIG_DIR", "TNS_ADMIN")
        kwargs = {"lib_dir": str(lib_dir.resolve())}
        if config_dir:
            kwargs["config_dir"] = str(Path(config_dir).resolve())
        oracledb.init_oracle_client(**kwargs)
    conn = oracledb.connect(user=user, password=password, dsn=dsn, program="RB1601")
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
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
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
        self.setWindowTitle('1601-X · Copiar Formulação de Produto Industrializado')
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
        self.target_table=self.create_table(['Excluir','Código','Matéria-prima / Componente','Un','Qtde','Fração','Etapa'])
        self.source_table.itemChanged.connect(self.on_table_change)
        self.target_table.itemChanged.connect(self.on_table_change)
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
            table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch)
            table.setColumnWidth(0,44)
            table.setColumnWidth(1,64)
            table.setColumnWidth(3,37)
            table.setColumnWidth(4,67)
            table.horizontalHeader().setSectionResizeMode(4,QHeaderView.ResizeToContents)
            table.setColumnWidth(5,54)
            table.setColumnWidth(6,102)
            if is_origin: table.setColumnWidth(7,42)
        bottom=QHBoxLayout()
        layout.addLayout(bottom)
        policy=QGroupBox('Tratamento de duplicidade')
        policy_layout=QGridLayout(policy)
        policy_layout.setContentsMargins(8,5,8,5)
        policy_layout.setSpacing(1)
        self.ignore=QRadioButton('Ignorar existentes')
        self.replace=QRadioButton('Substituir quantidade')
        self.sum=QRadioButton('Somar quantidades')
        self.ignore.setChecked(True)
        for row,(w,description) in enumerate((
            (self.ignore,'Mantém a quantidade no destino.'),
            (self.replace,'Usa a quantidade da origem.'),
            (self.sum,'Soma origem + destino.'),
        )):
            policy_layout.addWidget(w,row,0)
            help_label=QLabel(description)
            help_label.setWordWrap(True)
            policy_layout.addWidget(help_label,row,1)
            w.setToolTip(description)
            w.toggled.connect(self.invalidate_plan)
        bottom.addWidget(policy,3)
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
                          '🟨 Já existe no destino · ☑ Vínculo selecionado\n'
                          'Exclusões afetam apenas PCCOMPOSICAO.')
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
            QLabel,QRadioButton { color:#17232e; font-weight:normal; }
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

    def update_comparison(self,source_checks=None,target_checks=None):
        if source_checks is None:
            source_checks=[self.source_table.item(i,0).checkState() for i in range(self.source_table.rowCount())]
            if len(source_checks)!=len(self.source):source_checks=None
        if target_checks is None:
            target_checks=[self.target_table.item(i,0).checkState() for i in range(self.target_table.rowCount())]
            if len(target_checks)!=len(self.target):target_checks=None
        self.populate(source_checks,target_checks)
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

    def populate(self,selections=None,target_selections=None):
        source_blocker=QSignalBlocker(self.source_table)
        target_blocker=QSignalBlocker(self.target_table)
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
            check=QTableWidgetItem('')
            check.setFlags(Qt.ItemIsEnabled|Qt.ItemIsUserCheckable|Qt.ItemIsSelectable)
            check.setCheckState(target_selections[i] if target_selections is not None else Qt.Unchecked)
            self.target_table.setItem(i,0,check)
            etapa=(f'{r["NUMETAPA"]} - {r["DESC_ETAPA"]}' if r.get('NUMETAPA') and r.get('DESC_ETAPA') else r.get('NUMETAPA'))
            vals=[r['CODPROD'],r.get('DESC_COMPONENTE'),r.get('UNESTRUTURA') or r.get('UN_COMPONENTE'),fmt_qty(r.get('QT')),r.get('FRACAOUMIDA'),etapa]
            for j,val in enumerate(vals,1):self.target_table.setItem(i,j,make_item(val,color))
        self.invalidate_plan()

    def on_table_change(self,item):
        self.operation_completed=False
        self.invalidate_plan()

    def refresh_summary(self):
        if not hasattr(self,'summary'):return
        selected=sum(self.source_table.item(i,0).checkState()==Qt.Checked for i in range(self.source_table.rowCount()))
        existing=sum(any(self.collision(dict(s,METODO=self.method.currentText().strip()),t) for t in self.target) for s in self.source)
        self.summary.setText(f'Selecionados: {selected}\nNovos no destino: {max(0,selected-existing)}\nJá existentes: {existing}')

    def fingerprint(self,rows):
        # Snapshot de todos os campos técnicos usados na cópia, incluindo QT.
        return Counter(tuple(str(r.get(c)) for c in FIELDS) for r in rows)

    def build_plan(self,target=None,removals=None):
        if self.connection_uncertain:raise ValueError('A conexão foi interrompida. Reinicie a rotina e confira os dados no banco antes de tentar novamente.')
        if self.operation_completed:raise ValueError('Esta operação já foi concluída. Selecione os componentes para iniciar uma nova cópia.')
        if not self.origin_loaded or self.snapshot is None:raise ValueError('Aguarde a consulta da origem e do destino antes de confirmar.')
        if self.same_product_branch() and (self.method.currentText().strip()==self.origin_method.currentText().strip() or self.target):
            raise ValueError('Para copiar o mesmo produto na mesma filial, informe um método novo no destino.')
        if target is None:target=self.target
        if removals is None:
            removals={i for i in range(len(self.target)) if self.target_table.item(i,0).checkState()==Qt.Checked}
        inserts=[]
        updates={}
        selected=[dict(self.source[i],METODO=self.method.currentText().strip()) for i in range(len(self.source)) if self.source_table.item(i,0).checkState()==Qt.Checked]
        # Componentes da origem consolidados no mesmo método devem ser únicos.
        for i,a in enumerate(selected):
            for b in selected[:i]:
                if self.collision(a,b):
                    raise ValueError(f'O componente {a["CODPROD"]} se repete entre métodos da origem. Desmarque uma das linhas.')
        for cand in selected:
            if int(cand['CODPROD'])==self.dest.code:
                raise ValueError(f'O produto destino {self.dest.code} está selecionado como componente. Desmarque esse item na origem: um produto não pode fazer parte da própria composição.')
            matches=[j for j,t in enumerate(target) if self.collision(cand,t)]
            remaining=[j for j in matches if j not in removals]
            if len(remaining)>1:raise ValueError(f'Conflito múltiplo do componente {cand["CODPROD"]}. Revise os vínculos do destino.')
            if not remaining:
                inserts.append(cand)
            elif self.ignore.isChecked():
                continue
            else:
                j=remaining[0]
                old=target[j]
                source_unit=as_text(cand.get('UNESTRUTURA') or cand.get('UN_COMPONENTE')).strip().upper()
                target_unit=as_text(old.get('UNESTRUTURA') or old.get('UN_COMPONENTE')).strip().upper()
                if not source_unit or not target_unit or source_unit!=target_unit:
                    raise ValueError(f'O componente {cand["CODPROD"]} tem unidades incompatíveis: origem {source_unit or "não informada"}, destino {target_unit or "não informada"}. Não é possível somar ou substituir sem revisar as unidades.')
                if old.get('QT') is None or cand.get('QT') is None:
                    raise ValueError(f'Quantidade ausente no componente {cand["CODPROD"]}.')
                value=Decimal(str(cand['QT']))
                if self.sum.isChecked():value=exact_quantity_sum(value,old['QT'])
                updates[j]=value
        return {'inserts':inserts,'removals':sorted(removals),'updates':updates}

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
                scope.setText('Deseja copiar a estrutura selecionada para todas as filiais?')
                scope.setInformativeText(f'Escolha todas as filiais ou somente a filial {chosen}, selecionada no destino.')
                only=scope.addButton(f'Somente filial {chosen}',QMessageBox.AcceptRole)
                all_branches=scope.addButton('Todas as filiais',QMessageBox.ActionRole)
                scope.addButton(QMessageBox.Cancel)
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
                plan=self.build_plan() if branch==chosen else self.build_plan(target,removals=set())
                batches.append({'branch':branch,'target':target,'snapshot':self.snapshot if branch==chosen else self.fingerprint(target),'plan':plan})
            if not any(b['plan']['inserts'] or b['plan']['removals'] or b['plan']['updates'] for b in batches):
                QMessageBox.information(self,'Sem alterações','Nenhuma alteração a gravar.')
                return
            details=(f'Produto destino: {self.dest.code} | Método: {self.method.currentText()}\n'
                f'Filiais: {", ".join(branches)}\n'
                'O método de origem é preservado.\n\n'+
                '\n'.join(f'Filial {b["branch"]}: inserir {len(b["plan"]["inserts"])}, alterar {len(b["plan"]["updates"])}, excluir {len(b["plan"]["removals"])}' for b in batches)+
                '\n\nExclusões marcadas afetam somente a filial filtrada no destino.\n'
                'As alterações serão feitas no Oracle. Deseja continuar?')
            if QMessageBox.question(self,'Confirmar alterações',details,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
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
                    def where(row):
                        return {'p':operation['product'],'f':batch['branch'],'m':operation['method'],
                            'c':row['CODPROD'],'fr':row['FRACAOUMIDA'],'et':row['NUMETAPA']}
                    condition='''CODPRODMASTER=:p AND CODFILIAL=:f AND METODO=:m AND CODPROD=:c
                        AND (FRACAOUMIDA=:fr OR (FRACAOUMIDA IS NULL AND :fr IS NULL))
                        AND (NUMETAPA=:et OR (NUMETAPA IS NULL AND :et IS NULL))'''
                    for j in plan['removals']:
                        cur.execute('DELETE FROM PCCOMPOSICAO WHERE '+condition,where(batch['target'][j]))
                        if cur.rowcount!=1:raise ValueError('Exclusão não encontrou exatamente um vínculo.')
                    for j,value in plan['updates'].items():
                        cur.execute('UPDATE PCCOMPOSICAO SET QT=:qt WHERE '+condition,dict(where(batch['target'][j]),qt=value))
                        if cur.rowcount!=1:raise ValueError('Atualização não encontrou exatamente um vínculo.')
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
            QMessageBox.information(self,'Concluído','Formulação atualizada com sucesso. Operação finalizada; selecione novamente os componentes para iniciar outra cópia.')
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
        with QSignalBlocker(self.source_table),QSignalBlocker(self.target_table):
            for table in (self.source_table,self.target_table):
                for i in range(table.rowCount()):table.item(i,0).setCheckState(Qt.Unchecked)
        self.operation_completed=True
        self.invalidate_plan()
        self.statusBar().showMessage('Operação concluída. Selecione os componentes para iniciar uma nova cópia.')

if __name__=='__main__':
    app=QApplication(sys.argv)
    app.setStyle('Fusion')
    window=App()
    window.show()
    sys.exit(app.exec())
