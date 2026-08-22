from __future__ import annotations
from .dependencies import QMainWindow, Signal
from .mixins.calendar_page import CalendarPageMixin
from .mixins.crypto import CryptoMixin
from .mixins.dashboard import DashboardMixin
from .mixins.data_health import DataHealthMixin
from .mixins.dictionary_page import DictionaryPageMixin
from .mixins.etf_analyser import EtfAnalyserMixin
from .mixins.politics import PoliticsMixin
from .mixins.pre_market import PreMarketMixin
from .mixins.random_recommender import RandomRecommenderMixin
from .mixins.earnings_matrix_extract import EarningsMatrixExtractMixin
from .mixins.earnings_matrix_tables import EarningsMatrixTablesMixin
from .mixins.fundamentals_render import FundamentalsRenderMixin
from .mixins.fundamentals_setup import FundamentalsSetupMixin
from .mixins.global_page import GlobalPageMixin
from .mixins.ipo_page import IpoPageMixin
from .mixins.institutions import InstitutionsMixin
from .mixins.networth import NetWorthMixin
from .mixins.news import NewsMixin
from .mixins.options_chain import OptionsChainMixin
from .mixins.options_fetch import OptionsFetchMixin
from .mixins.options_table_events import OptionsTableEventsMixin
from .mixins.options_table_rows import OptionsTableRowsMixin
from .mixins.overview import OverviewMixin
from .mixins.price_page import PricePageMixin
from .mixins.economic_page import EconomicPageMixin
from .mixins.quant_page import QuantPageMixin
from .mixins.portfolio_metrics import PortfolioMetricsMixin
from .mixins.portfolio_setup import PortfolioSetupMixin
from .mixins.spy_heatmap import SpyHeatmapMixin
from .mixins.settings import SettingsMixin
from .mixins.signal_scanner2_page import SignalScanner2PageMixin
from .mixins.youtube import YouTubeMixin
from .mixins.backtest_page import BacktestPageMixin
from .mixins.charts_options_top_volume import ChartsOptionsTopVolumeMixin
from .mixins.charts_page import ChartsPageMixin
from .mixins.stocks_page import StocksPageMixin
from .mixins.strategies_page import StrategiesPageMixin
from .mixins.multi_charts import MultiChartsMixin
from .mixins.simple_charts import SimpleChartsMixin
from .mixins.theme_support import ThemeSupportMixin
from .mixins.up_down_page import UpDownPageMixin
from .mixins.valuation import ValuationMixin
from .mixins.window_bootstrap import WindowBootstrapMixin
from .mixins.window_lifecycle import WindowLifecycleMixin
from .mixins.window_setup import WindowSetupMixin


class BudgetTerminalApp(ThemeSupportMixin, DataHealthMixin, WindowBootstrapMixin, WindowSetupMixin, WindowLifecycleMixin, DashboardMixin, GlobalPageMixin, StrategiesPageMixin, SignalScanner2PageMixin, QuantPageMixin, EconomicPageMixin, UpDownPageMixin, ValuationMixin, FundamentalsSetupMixin, FundamentalsRenderMixin, EarningsMatrixExtractMixin, EarningsMatrixTablesMixin, SimpleChartsMixin, PortfolioSetupMixin, OptionsFetchMixin, OptionsTableRowsMixin, OptionsTableEventsMixin, PortfolioMetricsMixin, OptionsChainMixin, EtfAnalyserMixin, PreMarketMixin, CryptoMixin, RandomRecommenderMixin, IpoPageMixin, PoliticsMixin, InstitutionsMixin, YouTubeMixin, NewsMixin, DictionaryPageMixin, NetWorthMixin, CalendarPageMixin, OverviewMixin, PricePageMixin, SpyHeatmapMixin, SettingsMixin, ChartsPageMixin, ChartsOptionsTopVolumeMixin, BacktestPageMixin, StocksPageMixin, MultiChartsMixin, QMainWindow):
    _invoke_main = Signal(object)
