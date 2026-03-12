from __future__ import annotations
from typing import Any
from ..compat import *
from budget_terminal_app.paths import user_data_path

class PolygonSetupMixin:
    _P9_CONFIG_PATH = user_data_path('p9_config.json')

    def init_page9(self) -> None:
        """Build the Earnings Matrix page UI."""
        self.p9_current_data = None
        self.p9_em_mode = 'yoy'
        self.p9_em_visible_cols = 10
        self.p9_em_processed = {}
        layout = QVBoxLayout(self.page9)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        controls = QHBoxLayout()
        self.p9_api_key_input = QLineEdit()
        self.p9_api_key_input.setPlaceholderText('REST API Key')
        self.p9_api_key_input.setFixedWidth(150)
        self.p9_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.p9_s3_access_key = QLineEdit()
        self.p9_s3_access_key.setPlaceholderText('S3 Access Key')
        self.p9_s3_access_key.setFixedWidth(150)
        self.p9_s3_access_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.p9_s3_secret_key = QLineEdit()
        self.p9_s3_secret_key.setPlaceholderText('S3 Secret Key')
        self.p9_s3_secret_key.setFixedWidth(150)
        self.p9_s3_secret_key.setEchoMode(QLineEdit.EchoMode.Password)
        if self._P9_CONFIG_PATH.exists():
            try:
                with self._P9_CONFIG_PATH.open() as _f:
                    _p9_cfg = json.load(_f)
                    self.p9_api_key_input.setText(_p9_cfg.get('api_key', ''))
                    self.p9_s3_access_key.setText(_p9_cfg.get('s3_access_key', ''))
                    self.p9_s3_secret_key.setText(_p9_cfg.get('s3_secret_key', ''))
            except:
                pass
        self.p9_ticker_input = QLineEdit()
        self.p9_ticker_input.setPlaceholderText('Ticker')
        self.p9_ticker_input.setFixedWidth(80)
        self.p9_ticker_input.returnPressed.connect(self.analyze_stock_p9)
        self.p9_analyze_btn = QPushButton('Analyze')
        self.set_theme_variant(self.p9_analyze_btn, 'accent')
        self.p9_analyze_btn.clicked.connect(self.analyze_stock_p9)
        rest_label = QLabel('<b>REST API:</b>')
        self.set_theme_role(rest_label, 'section_title')
        controls.addWidget(rest_label)
        controls.addWidget(self.p9_api_key_input)
        controls.addSpacing(10)
        s3_label = QLabel('<b>S3 Access:</b>')
        self.set_theme_role(s3_label, 'section_title')
        controls.addWidget(s3_label)
        controls.addWidget(self.p9_s3_access_key)
        controls.addWidget(self.p9_s3_secret_key)
        controls.addSpacing(10)
        ticker_label = QLabel('<b>Ticker:</b>')
        self.set_theme_role(ticker_label, 'section_title')
        controls.addWidget(ticker_label)
        controls.addWidget(self.p9_ticker_input)
        controls.addWidget(self.p9_analyze_btn)
        controls.addStretch()
        layout.addLayout(controls)
        matrix_controls = QHBoxLayout()
        self.p9_metric_combo = QComboBox()
        for name, _, _, _, _ in P9_EM_METRICS:
            self.p9_metric_combo.addItem(name)
        self.p9_metric_combo.currentTextChanged.connect(self._p9_sync_render)
        self.p9_yoy_btn = QPushButton('YoY % Growth')
        self.p9_pop_btn = QPushButton('PoP % Growth')
        for btn in (self.p9_yoy_btn, self.p9_pop_btn):
            btn.setCheckable(True)
            btn.setFixedWidth(110)
        self.p9_yoy_btn.setChecked(True)
        self.p9_yoy_btn.clicked.connect(lambda: self._p9_em_set_growth_mode('yoy'))
        self.p9_pop_btn.clicked.connect(lambda: self._p9_em_set_growth_mode('pop'))
        self.p9_status_lbl = QLabel('Ready (Massive/Polygon Mode)')
        self.set_theme_role(self.p9_status_lbl, 'status_muted')
        metric_label = QLabel('<b>Metric:</b>')
        self.set_theme_role(metric_label, 'section_title')
        matrix_controls.addWidget(metric_label)
        matrix_controls.addWidget(self.p9_metric_combo)
        matrix_controls.addSpacing(20)
        matrix_controls.addWidget(self.p9_yoy_btn)
        matrix_controls.addWidget(self.p9_pop_btn)
        matrix_controls.addStretch()
        matrix_controls.addWidget(self.p9_status_lbl)
        layout.addLayout(matrix_controls)
        tables_container = QWidget()
        tables_layout = QVBoxLayout(tables_container)
        tables_layout.setContentsMargins(0, 0, 0, 0)
        v_box = QGroupBox('Raw Metric Values')
        self.set_theme_role(v_box, 'panel')
        v_layout = QVBoxLayout(v_box)
        self.p9_table_values = QTableWidget()
        self.p9_table_values.verticalHeader().setVisible(False)
        self.p9_table_values.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p9_table_values.setAlternatingRowColors(True)
        v_layout.addWidget(self.p9_table_values)
        tables_layout.addWidget(v_box)
        g_box = QGroupBox('Growth %')
        self.set_theme_role(g_box, 'panel')
        g_layout = QVBoxLayout(g_box)
        self.p9_table_growth = QTableWidget()
        self.p9_table_growth.verticalHeader().setVisible(False)
        self.p9_table_growth.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p9_table_growth.setAlternatingRowColors(True)
        g_layout.addWidget(self.p9_table_growth)
        tables_layout.addWidget(g_box)
        layout.addWidget(tables_container, 3)
        bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        chart_box = QGroupBox('Visualizations')
        self.set_theme_role(chart_box, 'panel')
        chart_layout = QVBoxLayout(chart_box)
        self.p9_plot_values = pg.PlotWidget(axisItems={'left': FmtAxisItem(orientation='left')})
        self.p9_plot_values.showGrid(x=True, y=True, alpha=0.15)
        chart_layout.addWidget(self.p9_plot_values)
        bottom_splitter.addWidget(chart_box)
        val_box = QGroupBox('Valuation Multiples')
        self.set_theme_role(val_box, 'panel')
        val_layout = QVBoxLayout(val_box)
        self.p9_valuation_table = QTableWidget(4, 5)
        self.p9_valuation_table.setHorizontalHeaderLabels(['Multiple', 'Last 4Q', 'Next 4Q', 'FY26 (E)', 'FY27 (E)'])
        self.p9_valuation_table.verticalHeader().setVisible(False)
        self.p9_valuation_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.p9_valuation_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.p9_valuation_table.setAlternatingRowColors(True)
        val_layout.addWidget(self.p9_valuation_table)
        bottom_splitter.addWidget(val_box)
        bottom_splitter.setStretchFactor(0, 2)
        bottom_splitter.setStretchFactor(1, 1)
        layout.addWidget(bottom_splitter, 1)

    def analyze_stock_p9(self) -> None:
        """Handle analyze stock p9."""
        ticker = self.p9_ticker_input.text().upper().strip()
        if not ticker:
            return
        api_key = self.p9_api_key_input.text().strip()
        s3_access = self.p9_s3_access_key.text().strip()
        s3_secret = self.p9_s3_secret_key.text().strip()
        if not api_key:
            self.set_status_text(self.p9_status_lbl, 'Error: API Key Required', status='negative')
            return
        try:
            with self._P9_CONFIG_PATH.open('w') as _f:
                json.dump({'api_key': api_key, 's3_access_key': s3_access, 's3_secret_key': s3_secret}, _f)
        except:
            pass
        self.p9_analyze_btn.setEnabled(False)
        self.set_status_text(self.p9_status_lbl, f'Loading {ticker} via Massive...', status='warning')
        self.p9_worker = P9PolygonWorker(ticker, api_key)
        self.p9_thread = QThread()
        self.p9_worker.moveToThread(self.p9_thread)
        self.p9_thread.started.connect(self.p9_worker.run)
        self.p9_worker.finished.connect(self.update_page9)
        self.p9_worker.finished.connect(self.p9_thread.quit)
        self.p9_worker.error.connect(lambda msg: (self.set_status_text(self.p9_status_lbl, f'Error: {msg}', status='negative'), self.p9_analyze_btn.setEnabled(True), self.p9_thread.quit()))
        self.p9_thread.start()

    def update_page9(self, data: Any) -> None:
        """Update page9."""
        self.p9_current_data = data
        self.p9_analyze_btn.setEnabled(True)
        self.set_status_text(self.p9_status_lbl, f"Data loaded for {data['ticker']} (Massive)", status='positive')
        self.p9_em_processed = self._p9_em_extract_data()
        self._p9_sync_render()

    def _apply_polygon_theme(self) -> None:
        """Refresh polygon page plot and status colors."""
        if hasattr(self, 'p9_plot_values'):
            self.style_plot_widget(self.p9_plot_values)
        if hasattr(self, 'p9_status_lbl'):
            self.set_status_text(self.p9_status_lbl, self.p9_status_lbl.text(), status=self.p9_status_lbl.property('bt_status') or 'muted')
