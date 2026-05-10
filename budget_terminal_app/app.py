from __future__ import annotations
from .dependencies import QMainWindow, pyqtSignal
from .mixins.calendar_page import CalendarPageMixin
from .mixins.dashboard import DashboardMixin
from .mixins.data_health import DataHealthMixin
from .mixins.etf_analyser import EtfAnalyserMixin
from .mixins.politics import PoliticsMixin
from .mixins.pre_market import PreMarketMixin
from .mixins.random_recommender import RandomRecommenderMixin
from .mixins.earnings_matrix_extract import EarningsMatrixExtractMixin
from .mixins.earnings_matrix_tables import EarningsMatrixTablesMixin
from .mixins.fundamentals_render import FundamentalsRenderMixin
from .mixins.fundamentals_setup import FundamentalsSetupMixin
from .mixins.networth import NetWorthMixin
from .mixins.news import NewsMixin
from .mixins.options_chain import OptionsChainMixin
from .mixins.options_fetch import OptionsFetchMixin
from .mixins.options_table_events import OptionsTableEventsMixin
from .mixins.options_table_rows import OptionsTableRowsMixin
from .mixins.portfolio_metrics import PortfolioMetricsMixin
from .mixins.portfolio_setup import PortfolioSetupMixin
from .mixins.sectors import SectorsMixin
from .mixins.spy_heatmap import SpyHeatmapMixin
from .mixins.settings import SettingsMixin
from .mixins.youtube import YouTubeMixin
from .mixins.charts_page import ChartsPageMixin
from .mixins.stocks_page import StocksPageMixin
from .mixins.multi_charts import MultiChartsMixin
from .mixins.simple_charts import SimpleChartsMixin
from .mixins.theme_support import ThemeSupportMixin
from .mixins.window_bootstrap import WindowBootstrapMixin
from .mixins.window_lifecycle import WindowLifecycleMixin
from .mixins.window_setup import WindowSetupMixin


class BudgetTerminalApp(ThemeSupportMixin, DataHealthMixin, WindowBootstrapMixin, WindowSetupMixin, WindowLifecycleMixin, DashboardMixin, FundamentalsSetupMixin, FundamentalsRenderMixin, EarningsMatrixExtractMixin, EarningsMatrixTablesMixin, SimpleChartsMixin, PortfolioSetupMixin, OptionsFetchMixin, OptionsTableRowsMixin, OptionsTableEventsMixin, PortfolioMetricsMixin, OptionsChainMixin, EtfAnalyserMixin, PreMarketMixin, RandomRecommenderMixin, PoliticsMixin, YouTubeMixin, NewsMixin, NetWorthMixin, CalendarPageMixin, SectorsMixin, SpyHeatmapMixin, SettingsMixin, ChartsPageMixin, StocksPageMixin, MultiChartsMixin, QMainWindow):
    _invoke_main = pyqtSignal(object)
