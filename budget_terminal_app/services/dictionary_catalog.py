from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Iterable

from .chart_pattern_catalog import CHART_PATTERN_CATALOG


@dataclass(frozen=True)
class DictionarySection:
    title: str
    body: str


@dataclass(frozen=True)
class DictionaryEntry:
    entry_id: str
    term: str
    aliases: tuple[str, ...]
    category: str
    definition: str
    why_it_matters: str
    sections: tuple[DictionarySection, ...] = ()
    keywords: tuple[str, ...] = ()
    related_entry_ids: tuple[str, ...] = ()
    chart_pattern_id: str | None = None


MARKET_BASICS = "Market Basics"
INSTRUMENTS = "Instruments"
TRADING_EXECUTION = "Trading & Execution"
INVESTING_PORTFOLIO = "Investing & Portfolio Management"
RISK_PERFORMANCE = "Risk & Performance"
FINANCIAL_STATEMENTS = "Financial Statements"
FUNDAMENTAL_ANALYSIS = "Fundamental Analysis"
VALUATION_FORMULAS = "Valuation & Formulas"
TECHNICAL_INDICATORS = "Technical Indicators"
CHART_PATTERNS = "Chart & Candlestick Patterns"
OPTIONS = "Options"
CORPORATE_ACTIONS = "Corporate Actions & Earnings"
MACRO_EVENTS = "Macroeconomics & Economic Events"
BEHAVIORAL_FINANCE = "Behavioral Finance"

DICTIONARY_CATEGORIES = (
    MARKET_BASICS,
    INSTRUMENTS,
    TRADING_EXECUTION,
    INVESTING_PORTFOLIO,
    RISK_PERFORMANCE,
    FINANCIAL_STATEMENTS,
    FUNDAMENTAL_ANALYSIS,
    VALUATION_FORMULAS,
    TECHNICAL_INDICATORS,
    CHART_PATTERNS,
    OPTIONS,
    CORPORATE_ACTIONS,
    MACRO_EVENTS,
    BEHAVIORAL_FINANCE,
)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value).casefold()).strip("-")
    return cleaned or "entry"


def _section(title: str, body: str) -> DictionarySection:
    return DictionarySection(title=str(title).strip(), body=str(body).strip())


def _entry(
    term: str,
    category: str,
    definition: str,
    why_it_matters: str,
    *,
    aliases: Iterable[str] = (),
    sections: Iterable[DictionarySection] = (),
    keywords: Iterable[str] = (),
    related: Iterable[str] = (),
    chart_pattern_id: str | None = None,
) -> DictionaryEntry:
    return DictionaryEntry(
        entry_id=_slug(term),
        term=term,
        aliases=tuple(aliases),
        category=category,
        definition=definition,
        why_it_matters=why_it_matters,
        sections=tuple(sections),
        keywords=tuple(keywords),
        related_entry_ids=tuple(_slug(value) for value in related),
        chart_pattern_id=chart_pattern_id,
    )


# Compact rows cover stable vocabulary. Formulas, scheduled releases, and chart
# patterns are expanded below because those subjects benefit from richer fields.
_CORE_ROWS: dict[str, tuple[tuple[str, str, str], ...]] = {
    MARKET_BASICS: (
        ("Ask", "The lowest displayed price at which a seller is willing to sell.", "A buyer crossing the spread normally executes near the ask."),
        ("Bid", "The highest displayed price at which a buyer is willing to buy.", "A seller crossing the spread normally executes near the bid."),
        ("Bid-Ask Spread", "The difference between the best bid and best ask.", "A wider spread increases the implicit cost of entering and exiting."),
        ("Bull Market", "A sustained market advance accompanied by broadly improving risk appetite.", "Market regime can affect trend persistence, valuations, and suitable risk controls."),
        ("Bear Market", "A sustained market decline, commonly described as a fall of at least 20% from a recent peak.", "Drawdowns often change correlations, liquidity, and investor behavior."),
        ("Correction", "A meaningful decline, commonly 10% or more, that is smaller than the conventional bear-market threshold.", "Corrections are normal but can expose leverage and weak risk controls."),
        ("Rally", "A sustained or sharp rise in a security or market.", "A rally can occur inside either a bull market or a longer bear market."),
        ("Market Capitalization", "The market value of a company's outstanding equity.", "It is widely used to compare company size and construct indexes."),
        ("Float", "Shares available for public trading after excluding closely held or restricted shares.", "A small float can amplify volatility and price impact."),
        ("Shares Outstanding", "All shares currently issued and held by investors, including restricted holdings.", "It is the denominator for per-share metrics and differs from public float."),
        ("Trading Volume", "The number of shares or contracts traded during a period.", "Volume helps assess liquidity and the participation behind a price move."),
        ("Turnover", "Trading volume expressed relative to shares outstanding or float.", "Turnover makes activity more comparable across companies of different sizes."),
        ("Liquidity", "The ability to trade promptly near the quoted price without materially moving the market.", "Poor liquidity raises spread, slippage, and exit risk."),
        ("Volatility", "The degree and speed of price variation over time.", "Volatility affects position sizing, option prices, and expected drawdowns."),
        ("Market Breadth", "The degree to which individual securities participate in a market move.", "Narrow leadership can make an index advance less robust than it appears."),
        ("Advance-Decline Line", "A cumulative measure of advancing issues minus declining issues.", "Divergence from an index may reveal strengthening or weakening breadth."),
        ("52-Week High", "The highest traded price during the preceding 52 weeks.", "It is a common reference for momentum, resistance, and investor anchoring."),
        ("52-Week Low", "The lowest traded price during the preceding 52 weeks.", "It is a common reference for downside momentum, support, and drawdown."),
        ("All-Time High", "The highest recorded market price for a security.", "Breaks to new highs remove historical overhead supply but do not guarantee continuation."),
        ("Market Cycle", "A recurring progression through expansion, peak, contraction, and recovery in prices or economic activity.", "Recognizing the cycle helps frame growth, valuation, and policy sensitivity."),
        ("Primary Market", "The market in which newly issued securities are sold by an issuer.", "Capital raised in a primary transaction goes to the issuer or selling holders."),
        ("Secondary Market", "The market in which investors trade securities already issued.", "Most daily stock exchange activity occurs in the secondary market."),
        ("Price Discovery", "The process through which buyers and sellers establish a market price.", "Transparent, liquid trading generally improves the quality of observed prices."),
        ("Efficient Market", "A market in which available information is rapidly incorporated into prices.", "The idea frames the difficulty of earning persistent risk-adjusted excess returns."),
    ),
    INSTRUMENTS: (
        ("Common Stock", "Equity ownership that usually carries voting rights and a residual claim on assets and earnings.", "Common shareholders receive value after creditors and preferred shareholders."),
        ("Preferred Stock", "A hybrid security with priority over common stock for dividends and liquidation, often without voting rights.", "Its return profile can resemble both equity and fixed income."),
        ("Exchange-Traded Fund", "A pooled fund whose shares trade on an exchange throughout the day.", "ETFs provide diversified or targeted exposure with stock-like execution."),
        ("Index Fund", "A fund designed to track a specified market index rather than select securities actively.", "Fees, tracking difference, and index methodology drive investor outcomes."),
        ("Mutual Fund", "A pooled investment vehicle priced at net asset value, normally once per trading day.", "Its dealing mechanics differ from intraday-traded ETFs."),
        ("Closed-End Fund", "A pooled fund with a generally fixed share count that trades on an exchange.", "Its market price can remain above or below its net asset value."),
        ("American Depositary Receipt", "A U.S.-traded certificate representing shares of a foreign company.", "ADRs add currency, custody, political, and home-market risks."),
        ("Real Estate Investment Trust", "A company or trust that owns or finances income-producing real estate under a qualifying tax structure.", "REITs offer listed real-estate exposure and often distribute substantial income."),
        ("Business Development Company", "A regulated investment company that finances smaller or developing businesses.", "BDCs can provide high income but carry credit and leverage risk."),
        ("Master Limited Partnership", "A publicly traded partnership, often used for energy infrastructure assets.", "Its distributions and tax reporting differ from ordinary corporate dividends."),
        ("Bond", "A debt security representing a contractual promise to pay interest and repay principal.", "Bond yields influence discount rates, financing costs, and equity valuations."),
        ("Treasury Security", "Debt issued by the U.S. federal government, including bills, notes, and bonds.", "Treasury yields are key benchmarks for risk-free rates and asset pricing."),
        ("Convertible Bond", "A bond that may be converted into a specified number of issuer shares.", "It combines credit exposure with equity upside and dilution potential."),
        ("Commercial Paper", "Short-term unsecured debt issued by corporations.", "Stress in commercial paper can signal tightening short-term funding conditions."),
        ("Money Market Fund", "A fund holding high-quality short-term debt instruments.", "It is used for cash management but is not identical to an insured bank deposit."),
        ("Commodity", "A standardized raw material such as oil, copper, wheat, or gold.", "Commodity prices can affect company margins, inflation, and sector performance."),
        ("Futures Contract", "A standardized agreement to buy or sell an asset at a future date and price.", "Futures are leveraged and widely used for hedging and price discovery."),
        ("Warrant", "A long-dated issuer-created right to purchase shares at a specified price.", "Exercise can create new shares and dilute existing owners."),
        ("Security", "A tradable financial instrument representing ownership, debt, or a contractual right.", "The security type determines the holder's legal claim and risk exposure."),
        ("Asset Class", "A group of investments with similar economic characteristics and risk drivers.", "Asset allocation decisions are commonly made at the asset-class level."),
    ),
    TRADING_EXECUTION: (
        ("Market Order", "An instruction to trade immediately at the best available prices.", "It prioritizes execution certainty over price certainty."),
        ("Limit Order", "An instruction to trade only at a specified price or better.", "It controls price but may never execute or may fill only partially."),
        ("Stop Order", "An order that becomes a market order after a trigger price is reached.", "Fast markets can produce fills far from the stop price."),
        ("Stop-Limit Order", "An order that becomes a limit order after its stop price is reached.", "It controls the worst permitted price but can fail to execute."),
        ("Trailing Stop", "A stop whose trigger follows favorable price movement by a fixed amount or percentage.", "It can protect gains while leaving room for a trend to continue."),
        ("Fill", "The execution of all or part of an order.", "Average fill price and filled quantity determine the realized trade."),
        ("Partial Fill", "Execution of only part of an order's requested quantity.", "Partial fills can leave unintended exposure or additional commissions."),
        ("Slippage", "The difference between an expected execution price and the actual fill price.", "Slippage rises with volatility, order size, and weak liquidity."),
        ("Price Impact", "The price movement caused by submitting or executing an order.", "Large orders may need to be staged to reduce market impact."),
        ("Time in Force", "The rule governing how long an order remains active.", "Choosing the wrong duration can create missed or unintended executions."),
        ("Day Order", "An order that expires if it is not filled by the end of the trading session.", "It prevents an old instruction from carrying into another session."),
        ("Good-Til-Canceled", "An order that remains open until filled, canceled, or expired by the broker.", "Long-lived orders should be reviewed as conditions change."),
        ("Immediate-or-Cancel", "An order requiring any available quantity to fill immediately, with the remainder canceled.", "It is useful when delayed or resting exposure is undesirable."),
        ("Fill-or-Kill", "An order requiring the entire quantity to fill immediately or be canceled.", "It avoids partial positions but sharply reduces execution probability."),
        ("All-or-None", "An instruction not to execute unless the full requested quantity can be filled.", "It may delay or prevent fills in less liquid securities."),
        ("Opening Auction", "An exchange process that matches accumulated orders to establish an opening price.", "The auction can concentrate liquidity and overnight price discovery."),
        ("Closing Auction", "An exchange process that matches orders to establish the official closing price.", "Index funds and institutional benchmarks create heavy closing-auction volume."),
        ("Pre-Market Trading", "Trading before the primary exchange's regular session.", "Liquidity is often thinner and spreads wider than during regular hours."),
        ("After-Hours Trading", "Trading after the primary exchange's regular session.", "Earnings reactions often occur here, with heightened gap and liquidity risk."),
        ("Short Sale", "A sale of borrowed shares with the intention of repurchasing them later.", "Losses can be theoretically unlimited if price rises."),
        ("Short Interest", "Shares sold short that remain open, usually reported as a quantity or percentage of float.", "High short interest can reflect bearish conviction and squeeze risk."),
        ("Days to Cover", "Short interest divided by average daily trading volume.", "A high value suggests shorts may need more time to exit."),
        ("Short Squeeze", "A rapid rise intensified by short sellers buying shares to close positions.", "Squeeze-driven prices can detach temporarily from fundamentals."),
        ("Margin Account", "A brokerage account that permits borrowing against securities.", "Borrowing magnifies gains, losses, interest expense, and liquidation risk."),
        ("Margin Call", "A demand to add capital or reduce exposure after account equity falls below a requirement.", "Failure to meet it can lead to forced liquidation."),
        ("Circuit Breaker", "A rule that pauses trading after specified market moves or abnormal conditions.", "Pauses allow information and orders to rebalance during disorderly markets."),
        ("Trading Halt", "A temporary suspension of trading in a security or market.", "Orders may face gap risk when trading resumes."),
        ("Uptick Rule", "A short-sale restriction that can apply after a significant one-day decline.", "It limits certain short executions during acute downward pressure."),
        ("Payment for Order Flow", "Compensation a broker receives for routing customer orders to a trading venue or market maker.", "It raises questions about execution quality and conflicts of interest."),
        ("Best Execution", "A broker's duty to seek the most favorable reasonably available execution terms.", "Price improvement, speed, likelihood, and total cost all matter."),
    ),
    INVESTING_PORTFOLIO: (
        ("Asset Allocation", "The division of capital among asset classes or exposure groups.", "Allocation usually drives more portfolio risk than individual security selection."),
        ("Diversification", "Spreading exposure across investments with different risk drivers.", "It can reduce idiosyncratic risk but cannot eliminate market risk."),
        ("Concentration", "A large share of a portfolio invested in a small number of exposures.", "Concentration increases both upside participation and loss severity."),
        ("Position Size", "The amount of capital or risk assigned to an investment.", "Sizing converts an investment view into actual portfolio impact."),
        ("Rebalancing", "Restoring a portfolio toward target weights by trading or directing new cash.", "Rebalancing controls drift and can impose a buy-low, sell-high discipline."),
        ("Dollar-Cost Averaging", "Investing a fixed amount at regular intervals regardless of price.", "It reduces timing dependence but does not guarantee a profit."),
        ("Lump-Sum Investing", "Deploying available capital at one time rather than in stages.", "It gains immediate market exposure but carries greater entry-timing risk."),
        ("Buy and Hold", "Owning investments through market fluctuations for a long horizon.", "It minimizes trading friction but still requires thesis and risk review."),
        ("Value Investing", "Seeking securities priced below a reasoned estimate of intrinsic value.", "The approach depends on valuation quality and patience, not merely low multiples."),
        ("Growth Investing", "Seeking companies expected to expand earnings or cash flow faster than peers.", "Growth stocks are often especially sensitive to expectations and discount rates."),
        ("Quality Investing", "Favoring durable businesses with strong economics, balance sheets, and governance.", "Quality can reduce fundamental fragility but may command a high valuation."),
        ("Momentum Investing", "Favoring securities with strong recent relative or absolute performance.", "Momentum can persist but is vulnerable to abrupt factor reversals."),
        ("Income Investing", "Prioritizing cash distributions such as dividends or interest.", "A high yield is only valuable when the payment and principal are sustainable."),
        ("Contrarian Investing", "Taking positions against prevailing sentiment after independent analysis.", "Being different is useful only when the consensus is actually wrong."),
        ("Investment Horizon", "The expected length of time an investment will be held.", "Horizon affects suitable volatility, liquidity, and valuation assumptions."),
        ("Risk Tolerance", "An investor's willingness and capacity to accept losses and uncertainty.", "A portfolio that exceeds tolerance is unlikely to be held through stress."),
        ("Investment Thesis", "A testable explanation for why an investment should deliver an attractive outcome.", "Clear drivers, valuation, catalysts, and invalidation conditions improve decisions."),
        ("Catalyst", "An identifiable event that could cause the market to reassess a security.", "A catalyst can shorten the time between thesis and price realization."),
        ("Watchlist", "A monitored list of securities that are not necessarily owned.", "It supports disciplined preparation before a price or thesis trigger occurs."),
        ("Benchmark", "A reference index or return series used to evaluate a portfolio.", "The benchmark should reflect the portfolio's investable opportunity set and risk."),
        ("Tracking Error", "The variability of a portfolio's return difference versus its benchmark.", "It measures active risk rather than whether active decisions were profitable."),
        ("Home Bias", "A preference for domestic investments beyond their weight in the global opportunity set.", "It can reduce currency complexity but increase geographic concentration."),
    ),
    RISK_PERFORMANCE: (
        ("Systematic Risk", "Risk arising from broad market factors that diversification cannot remove.", "Equity beta, rates, and recessions can affect many holdings simultaneously."),
        ("Idiosyncratic Risk", "Company- or security-specific risk that can be reduced through diversification.", "A single position can damage a concentrated portfolio even when the market is stable."),
        ("Downside Risk", "The possibility and severity of returns below a target or acceptable threshold.", "Investors often experience losses asymmetrically compared with gains."),
        ("Tail Risk", "The risk of rare, extreme outcomes outside ordinary expectations.", "Leverage and liquidity mismatch can make tail events especially damaging."),
        ("Drawdown", "The decline from a portfolio or security's prior peak to a subsequent trough.", "Drawdown measures the lived path of losses rather than average variability."),
        ("Recovery Time", "The time required to regain a prior peak after a drawdown.", "Deep losses require disproportionately large gains and can impair compounding."),
        ("Correlation", "The degree to which two return series move together.", "Diversification benefits depend on correlations, which can rise during crises."),
        ("Covariance", "A scale-dependent measure of how two variables vary together.", "It is an input to portfolio variance and optimization."),
        ("Value at Risk", "An estimate of the loss threshold not expected to be exceeded at a chosen confidence level and horizon.", "It summarizes ordinary tail exposure but says little about losses beyond the threshold."),
        ("Stress Test", "An assessment of portfolio behavior under a severe hypothetical or historical scenario.", "It exposes nonlinear, concentrated, and liquidity risks hidden by averages."),
        ("Scenario Analysis", "Evaluation of outcomes under coherent sets of assumptions.", "It makes uncertainty explicit instead of relying on one forecast."),
        ("Risk-Adjusted Return", "Return evaluated relative to the risk taken to earn it.", "Raw returns can reward hidden leverage or concentration."),
        ("Active Return", "A portfolio's return minus its benchmark return.", "It isolates the result of deviating from the benchmark."),
        ("Information Ratio", "Active return divided by tracking error.", "It measures how consistently active risk produced excess return."),
        ("Risk Budget", "A limit or allocation for how much portfolio risk an exposure may contribute.", "Risk budgeting prevents capital weights from disguising volatile positions."),
        ("Hedging", "Taking an offsetting exposure intended to reduce a specified risk.", "Hedges have costs, basis risk, and may reduce upside as well as downside."),
        ("Leverage", "Use of borrowing or derivatives to increase exposure relative to capital.", "Leverage magnifies returns and can force liquidation at the worst time."),
        ("Liquidity Risk", "The risk that a position cannot be traded quickly near a reasonable price.", "Quoted prices may be unavailable when many investors seek the same exit."),
    ),
    FINANCIAL_STATEMENTS: (
        ("Income Statement", "A statement of revenue, expenses, and profit over a period.", "It explains reported profitability but not necessarily cash generation."),
        ("Balance Sheet", "A snapshot of assets, liabilities, and shareholders' equity at a date.", "It reveals financing, liquidity, and accumulated capital."),
        ("Cash Flow Statement", "A statement reconciling cash changes across operating, investing, and financing activities.", "It helps test whether accounting earnings convert into cash."),
        ("Revenue", "The value of goods or services recognized from ordinary business activity.", "Growth quality depends on price, volume, mix, timing, and collectability."),
        ("Cost of Goods Sold", "Direct costs attributable to producing goods or delivering services sold.", "Its relationship to revenue determines gross profit."),
        ("Gross Profit", "Revenue minus cost of goods sold.", "It shows the economic surplus available before operating expenses."),
        ("Operating Expense", "Costs of running the business that are not included in cost of goods sold.", "Expense discipline affects operating leverage and profitability."),
        ("Operating Income", "Profit after operating costs but before interest and taxes.", "It focuses on the economics of core operations."),
        ("Net Income", "Profit remaining after all recognized expenses, interest, and taxes.", "It belongs to shareholders but may differ materially from cash flow."),
        ("Earnings Before Interest and Taxes", "Operating-oriented profit before financing cost and income tax.", "EBIT helps compare operations across capital structures."),
        ("EBITDA", "Earnings before interest, taxes, depreciation, and amortization.", "It is a common operating proxy but is not cash flow."),
        ("Depreciation", "Allocation of a tangible asset's cost over its useful life.", "It lowers accounting profit and signals the consumption of productive assets."),
        ("Amortization", "Allocation of an intangible asset or financing cost over time.", "Different types have different implications for recurring economics."),
        ("Accounts Receivable", "Amounts customers owe for recognized sales not yet collected.", "Rapid receivable growth can weaken cash conversion or signal credit risk."),
        ("Inventory", "Goods held for sale or used in production.", "Excess or obsolete inventory can cause markdowns and cash strain."),
        ("Accounts Payable", "Amounts owed to suppliers for purchases already received.", "Payables provide operating financing but cannot grow indefinitely."),
        ("Working Capital", "Current operating assets minus current operating liabilities, or more broadly current assets minus current liabilities.", "Changes in working capital can consume or release cash."),
        ("Capital Expenditure", "Cash spent to acquire or improve long-lived assets.", "Maintenance and growth capex affect free cash flow differently."),
        ("Goodwill", "An acquisition asset representing purchase price above identifiable net assets.", "Impairment can reveal that expected acquisition benefits did not materialize."),
        ("Deferred Revenue", "Cash received before the related revenue is recognized.", "It can provide financing and visibility but is accompanied by a delivery obligation."),
        ("Stock-Based Compensation", "Compensation paid with equity instruments or equity-linked awards.", "It is noncash when recorded but economically dilutes owners."),
        ("Noncontrolling Interest", "The portion of a consolidated subsidiary not owned by the reporting parent.", "Enterprise and equity value calculations must treat it consistently."),
        ("Retained Earnings", "Cumulative profit retained in the business after dividends and certain adjustments.", "It shows historical reinvestment but not the current cash balance."),
        ("Comprehensive Income", "Net income plus specified gains and losses recorded outside net income.", "It captures some economic changes omitted from the income statement."),
    ),
    FUNDAMENTAL_ANALYSIS: (
        ("Fundamental Analysis", "Assessment of a security using business economics, financial statements, industry conditions, and valuation.", "It links an investment decision to the underlying enterprise rather than price alone."),
        ("Economic Moat", "A durable advantage that protects returns from competition.", "A real moat can sustain margins, growth, and reinvestment opportunities."),
        ("Pricing Power", "The ability to raise prices without losing unacceptable demand.", "Pricing power can defend margins against inflation and competition."),
        ("Operating Leverage", "The sensitivity of operating profit to revenue changes because some costs are fixed.", "It amplifies both earnings growth and earnings declines."),
        ("Financial Leverage", "Use of debt or fixed financing claims in a company's capital structure.", "It can raise equity returns but also default and refinancing risk."),
        ("Unit Economics", "Revenue and costs associated with one customer, product, or transaction unit.", "Attractive unit economics are essential when growth requires repeated acquisition spending."),
        ("Total Addressable Market", "The maximum theoretical revenue opportunity for a product or service.", "It frames runway but can be overstated without realistic segmentation."),
        ("Market Share", "A company's sales or units as a percentage of its defined market.", "Share trends help distinguish company execution from industry growth."),
        ("Organic Growth", "Growth generated by existing operations rather than acquisitions or currency translation.", "It is often a cleaner measure of underlying demand and execution."),
        ("Same-Store Sales", "Sales growth from locations open for a defined comparable period.", "It separates existing-location performance from expansion."),
        ("Backlog", "Contracted or ordered work not yet recognized as revenue.", "Backlog may improve visibility but can be canceled, delayed, or low margin."),
        ("Bookings", "The value of customer orders or contracts signed during a period.", "Bookings can be a leading indicator of future revenue."),
        ("Book-to-Bill Ratio", "Bookings divided by recognized revenue or billings for the same period.", "A ratio above one can indicate expanding demand and backlog."),
        ("Customer Acquisition Cost", "Sales and marketing cost required to acquire a new customer.", "It should be evaluated against customer lifetime value and payback time."),
        ("Customer Lifetime Value", "Estimated contribution generated by a customer over the relationship.", "Optimistic retention or margin assumptions can make the metric misleading."),
        ("Churn", "The rate at which customers or recurring revenue are lost.", "Small churn changes can materially affect subscription economics."),
        ("Net Revenue Retention", "Recurring revenue retained from an existing customer cohort after expansion, contraction, and churn.", "Values above 100% indicate expansion exceeds losses within the cohort."),
        ("Recurring Revenue", "Revenue expected to repeat under subscriptions, contracts, or repeat-purchase behavior.", "Durability and renewal economics matter more than the label alone."),
        ("Cyclicality", "Sensitivity of business results to economic or industry cycles.", "Peak-cycle earnings can make a cyclical company appear deceptively cheap."),
        ("Secular Growth", "Long-duration growth driven by structural rather than cyclical forces.", "A secular tailwind can expand opportunity but may become overvalued."),
        ("Management Guidance", "A company's forecast or qualitative outlook for future performance.", "Changes versus prior guidance and expectations often drive stock reactions."),
        ("Segment Reporting", "Disclosure of financial results for distinct business components.", "Segments reveal different growth, margin, and capital characteristics hidden by totals."),
    ),
    VALUATION_FORMULAS: (
        ("Intrinsic Value", "An estimate of an asset's economic worth based on expected future benefits and risk.", "It provides a decision anchor independent of the current quote."),
        ("Relative Valuation", "Valuing a company by comparing multiples with peers, history, or transactions.", "Comparability and normalized fundamentals matter more than a low headline multiple."),
        ("Discounted Cash Flow", "A valuation method that discounts forecast cash flows to present value.", "It makes growth, margins, reinvestment, and required return assumptions explicit."),
        ("Comparable Company Analysis", "A valuation method using trading multiples of similar public companies.", "Peer selection and metric consistency strongly influence the result."),
        ("Precedent Transaction Analysis", "A valuation method using prices paid in comparable acquisitions.", "Control premiums and cycle conditions can make deal multiples unlike public trading values."),
        ("Sum-of-the-Parts Valuation", "A method that values business segments separately and then combines them.", "It is useful when segments have different economics or appropriate peer groups."),
        ("Margin of Safety", "The discount between price and a conservative estimate of value.", "It provides room for analytical error and adverse outcomes."),
        ("Multiple Expansion", "An increase in the valuation multiple investors assign to a financial metric.", "Returns can exceed business growth when sentiment or rates lift the multiple."),
        ("Multiple Compression", "A decrease in the valuation multiple assigned to a financial metric.", "A company can grow earnings while its share price falls if the multiple contracts enough."),
        ("Terminal Value", "The estimated value of cash flows beyond an explicit forecast period.", "It often represents a large share of DCF value and demands conservative assumptions."),
        ("Discount Rate", "The required return used to convert future cash flows into present value.", "Small rate changes can materially affect long-duration valuations."),
        ("Sensitivity Analysis", "A table or process showing how an output changes when key assumptions change.", "It reveals which assumptions dominate a valuation conclusion."),
    ),
    TECHNICAL_INDICATORS: (
        ("Technical Analysis", "Study of price, volume, and market behavior to evaluate trend, momentum, and potential levels.", "It can structure entries and risk, but patterns are probabilistic rather than predictive certainties."),
        ("Support", "A price area where buying has previously been strong enough to slow a decline.", "A break or hold can inform risk levels, but support is a zone rather than a guarantee."),
        ("Resistance", "A price area where selling has previously been strong enough to slow an advance.", "Repeated tests can either validate the level or consume available supply."),
        ("Trend", "The prevailing direction and structure of price movement.", "Trading with or against the dominant trend changes expected win rate and risk."),
        ("Uptrend", "A price structure generally characterized by higher highs and higher lows.", "A broken sequence can warn that trend strength is changing."),
        ("Downtrend", "A price structure generally characterized by lower highs and lower lows.", "Rallies inside a downtrend may remain countertrend until structure changes."),
        ("Sideways Market", "A range-bound market without a sustained directional trend.", "Trend-following signals often whipsaw when price remains in a range."),
        ("Breakout", "A move beyond a defined resistance, support, range, or pattern boundary.", "Confirmation, volume, and follow-through help distinguish a breakout from noise."),
        ("Breakdown", "A downside move through a defined support or pattern boundary.", "Failed breakdowns can reverse sharply when sellers are trapped."),
        ("False Breakout", "A move beyond a level that quickly returns inside the prior structure.", "Waiting for confirmation can reduce, but not eliminate, false-signal risk."),
        ("Retest", "A return to a recently broken level or boundary.", "A successful retest can clarify support, resistance, and invalidation."),
        ("Momentum", "The strength and persistence of price movement.", "Momentum can confirm a trend or diverge before a possible reversal."),
        ("Divergence", "A disagreement between price direction and an indicator or related series.", "Divergence is a warning condition, not a standalone timing signal."),
        ("Volume-Weighted Average Price", "The average traded price weighted by volume during a chosen period.", "VWAP is a common intraday benchmark and institutional execution reference."),
        ("Average True Range", "A volatility indicator based on the largest of three daily range measures.", "ATR helps scale stops and position sizes to current volatility."),
        ("Bollinger Bands", "A moving average surrounded by bands set a chosen number of standard deviations away.", "Band width and price location describe volatility and relative extension."),
        ("Stochastic Oscillator", "A momentum oscillator comparing the close with the recent high-low range.", "Overbought or oversold readings require trend context."),
        ("Money Flow Index", "A volume-weighted momentum oscillator derived from price and volume.", "It adds participation information to an RSI-like framework."),
        ("On-Balance Volume", "A cumulative indicator that adds volume on up closes and subtracts it on down closes.", "Its trend can help assess whether volume confirms price."),
        ("Accumulation", "A period in which informed or persistent buying absorbs available supply.", "Accumulation is inferred from behavior and cannot be known from price alone."),
        ("Distribution", "A period in which persistent selling transfers shares to other buyers.", "Distribution can precede weakness but requires confirmation."),
        ("Golden Cross", "A bullish moving-average crossover, commonly the 50-day average moving above the 200-day average.", "It is lagging and works best with broader trend confirmation."),
        ("Death Cross", "A bearish moving-average crossover, commonly the 50-day average moving below the 200-day average.", "It is lagging and may occur after much of a decline."),
        ("Fibonacci Retracement", "Horizontal reference levels based on selected Fibonacci ratios applied to a price move.", "Traders watch them as potential reaction zones, not causal laws."),
    ),
    CHART_PATTERNS: (
        ("Doji", "A candlestick with nearly equal opening and closing prices.", "It signals indecision and needs location and follow-through for meaning."),
        ("Hammer", "A candle with a small real body near the high and a long lower shadow after weakness.", "It can show rejection of lower prices when confirmed by subsequent action."),
        ("Hanging Man", "A hammer-shaped candle appearing after an advance.", "Its context makes it a potential warning rather than a bullish reversal candle."),
        ("Inverted Hammer", "A candle with a small body near the low and a long upper shadow after a decline.", "Bullish confirmation is needed because sellers still pushed price off the high."),
        ("Shooting Star", "A candle with a small body near the low and a long upper shadow after an advance.", "It can show rejection of higher prices when the next action confirms weakness."),
        ("Bullish Engulfing", "A two-candle pattern in which a bullish real body engulfs the prior bearish real body.", "It can mark a shift in control after a decline or at support."),
        ("Bearish Engulfing", "A two-candle pattern in which a bearish real body engulfs the prior bullish real body.", "It can mark a shift in control after an advance or at resistance."),
        ("Morning Star", "A three-candle bullish reversal sequence with weakness, hesitation, then a strong recovery.", "The third candle provides evidence that buyers regained control."),
        ("Evening Star", "A three-candle bearish reversal sequence with strength, hesitation, then a strong decline.", "The third candle provides evidence that sellers regained control."),
        ("Inside Bar", "A candle whose high-low range sits within the preceding candle's range.", "It represents compression that can resolve in either direction."),
        ("Outside Bar", "A candle whose range exceeds both the high and low of the preceding candle.", "It signals range expansion but direction depends on close and context."),
        ("Marubozu", "A large-bodied candle with very small or absent shadows.", "It reflects strong directional control during that period."),
        ("Spinning Top", "A small-bodied candle with meaningful upper and lower shadows.", "It reflects two-sided trading and indecision rather than a complete signal."),
        ("Gap", "A price interval between sessions in which no trading occurred.", "Gaps can mark new information, low liquidity, or important support and resistance."),
        ("Gap Up", "An opening above the prior session's trading range or close.", "Whether the gap holds helps evaluate demand after new information."),
        ("Gap Down", "An opening below the prior session's trading range or close.", "Whether the gap fills or extends helps evaluate selling pressure."),
    ),
    OPTIONS: (
        ("Call Option", "A contract giving the holder the right, not the obligation, to buy the underlying at the strike price.", "Calls provide leveraged upside with a finite life and premium at risk."),
        ("Put Option", "A contract giving the holder the right, not the obligation, to sell the underlying at the strike price.", "Puts can express downside views or hedge existing shares."),
        ("Strike Price", "The contractual price at which an option may be exercised.", "Moneyness and payoff depend on the strike relative to the underlying."),
        ("Expiration Date", "The final date on which an option retains contractual life.", "Time value normally decays as expiration approaches."),
        ("Option Premium", "The price paid by an option buyer and received by its seller.", "Premium reflects intrinsic value, time, volatility, rates, and dividends."),
        ("Option Intrinsic Value", "The immediate exercise value of an option, never below zero.", "It separates exercise value from time value in the premium."),
        ("Time Value", "The portion of an option premium above intrinsic value.", "It compensates the seller for the possibility of favorable movement before expiration."),
        ("In the Money", "An option with positive intrinsic value.", "Moneyness affects delta, exercise value, and sensitivity to time decay."),
        ("At the Money", "An option whose strike is near the underlying price.", "Time value and gamma are often most important near at-the-money strikes."),
        ("Out of the Money", "An option with no intrinsic value at the current underlying price.", "It must move favorably before expiration to finish with exercise value."),
        ("Implied Volatility", "The volatility input consistent with an option's market price under a pricing model.", "It represents the price of expected uncertainty, not a guaranteed forecast."),
        ("Historical Volatility", "Volatility calculated from past underlying returns.", "Comparing it with implied volatility helps frame option richness, with important caveats."),
        ("Delta", "The approximate change in option price for a one-unit change in the underlying, all else equal.", "It also describes directional exposure and changes with price and time."),
        ("Gamma", "The rate at which delta changes as the underlying price changes.", "High gamma creates rapidly changing directional exposure."),
        ("Theta", "The model-estimated change in option value from one day of time passing, all else equal.", "Option buyers generally pay and sellers generally collect time decay."),
        ("Vega", "The option price sensitivity to a one-percentage-point change in implied volatility.", "Long-dated and near-the-money options often carry substantial vega."),
        ("Rho", "The option price sensitivity to a change in interest rates.", "Rho matters more for longer-dated contracts and larger rate moves."),
        ("Open Interest", "The number of option contracts still open at the end of a reporting period.", "It indicates outstanding positioning but not whether traders are bullish or bearish."),
        ("Option Volume", "The number of option contracts traded during a period.", "Unusual volume can signal attention but requires context and trade-direction evidence."),
        ("Assignment", "The obligation imposed on an option writer when a holder exercises.", "American-style options can be assigned before expiration."),
        ("Exercise", "Use of an option right to buy or sell the underlying at the strike.", "Exercise can create stock, cash, tax, and funding consequences."),
        ("Covered Call", "Long shares combined with a short call on those shares.", "It earns premium in exchange for capping upside and retaining most downside."),
        ("Protective Put", "Long shares combined with a long put.", "It creates a downside floor for the cost of the put premium."),
        ("Cash-Secured Put", "A short put backed by enough cash to purchase shares if assigned.", "It earns premium while accepting the obligation to buy at the strike."),
        ("Vertical Spread", "Long and short options of the same type and expiration at different strikes.", "It defines maximum gain and loss while reducing premium relative to a single leg."),
        ("Iron Condor", "A limited-risk position combining an out-of-the-money call spread and put spread.", "It generally benefits when price remains within a range and implied volatility falls."),
        ("Straddle", "A call and put with the same strike and expiration, both long or both short.", "A long straddle needs a large move; a short straddle accepts substantial tail risk."),
        ("Strangle", "A call and put with different strikes but the same expiration, both long or both short.", "It is cheaper than a comparable straddle when long but requires a larger move."),
        ("Early Assignment Risk", "The risk that an American-style short option is exercised before expiration.", "It rises around dividends and when remaining time value is small."),
        ("Pin Risk", "Uncertainty about exercise and assignment when the underlying closes near a strike at expiration.", "It can leave an unexpected stock position after the market closes."),
    ),
    CORPORATE_ACTIONS: (
        ("Dividend", "A distribution of corporate value to shareholders, usually paid in cash or shares.", "Yield alone does not show whether the payment is sustainable."),
        ("Ex-Dividend Date", "The first date a buyer is not entitled to the declared dividend under normal settlement.", "The stock price commonly adjusts for the distribution, all else equal."),
        ("Record Date", "The date on which the company identifies shareholders entitled to a distribution or vote.", "Settlement timing links eligibility to the ex-dividend date."),
        ("Dividend Reinvestment Plan", "A program that uses dividends to purchase additional shares.", "It automates compounding but does not remove valuation or concentration risk."),
        ("Special Dividend", "A nonrecurring distribution outside the normal dividend schedule.", "It can return excess capital but should not be annualized as ordinary income."),
        ("Share Repurchase", "A company purchase of its own shares.", "Repurchases add value when executed below intrinsic value and funded prudently."),
        ("Stock Split", "An increase in share count with a proportional decrease in price per share.", "It changes trading units, not the company's total equity value by itself."),
        ("Reverse Stock Split", "A reduction in share count with a proportional increase in price per share.", "It changes trading units and may be used to meet listing requirements."),
        ("Spin-Off", "Distribution of shares in a subsidiary or business to existing shareholders.", "Separate ownership can reveal value but creates standalone execution risks."),
        ("Merger", "A transaction combining two companies into one economic organization.", "Consideration, approvals, synergies, financing, and antitrust risk affect outcomes."),
        ("Acquisition", "Purchase of control of a company or business.", "The buyer's value depends on price paid, integration, and realized economics."),
        ("Tender Offer", "A public offer to purchase shares directly from shareholders under specified terms.", "Terms, proration, conditions, and competing bids determine value."),
        ("Rights Offering", "An offer allowing existing shareholders to buy newly issued shares, often at a discount.", "Nonparticipating owners may be diluted."),
        ("Secondary Offering", "A sale of additional shares by the company or existing holders after the IPO.", "Primary issuance raises capital and dilutes; holder sales do not fund the company."),
        ("Initial Public Offering", "The first public sale and listing of a company's shares.", "Limited history, lockups, allocation, and price discovery can create volatility."),
        ("Lockup Period", "A period restricting specified insiders from selling shares after an offering or transaction.", "Expiration can increase available supply but does not ensure selling."),
        ("Earnings Release", "A company's periodic report of financial results and business updates.", "Price reactions depend on results versus expectations and the revised outlook."),
        ("Earnings Call", "A management presentation and question-and-answer session accompanying results.", "Commentary can reveal drivers, risks, and changes not obvious in headline numbers."),
        ("Earnings Surprise", "The difference between reported earnings and the consensus estimate.", "A beat or miss matters in relation to quality, guidance, and priced expectations."),
        ("Whisper Number", "An unofficial expectation that may differ from the published consensus.", "A stock can fall after an official beat if investors expected more."),
        ("Form 10-K", "A U.S. public company's comprehensive annual filing with audited statements and risk disclosures.", "It is a primary source for long-form fundamental analysis."),
        ("Form 10-Q", "A U.S. public company's quarterly filing with unaudited interim financial information.", "It updates financials, risks, and management discussion between annual reports."),
        ("Form 8-K", "A U.S. filing used to report specified material events.", "It can disclose acquisitions, leadership changes, financings, and results promptly."),
        ("Proxy Statement", "A filing providing voting matters, governance, ownership, and executive compensation information.", "It helps evaluate incentives, dilution, and board accountability."),
        ("Insider Transaction", "A purchase or sale by a company insider subject to disclosure rules.", "Transactions require context because diversification and compensation can drive them."),
    ),
    MACRO_EVENTS: (
        ("Monetary Policy", "Central-bank actions affecting money, credit, rates, and financial conditions.", "Policy changes alter discount rates, demand, currencies, and risk appetite."),
        ("Fiscal Policy", "Government taxation and spending decisions.", "Fiscal changes can affect growth, inflation, sector demand, and public borrowing."),
        ("Inflation", "A sustained rise in the general price level.", "Inflation affects purchasing power, margins, interest rates, and valuation multiples."),
        ("Deflation", "A sustained decline in the general price level.", "It can increase real debt burdens and discourage spending or investment."),
        ("Disinflation", "A slowing rate of inflation while the price level continues to rise.", "Markets may respond differently to disinflation than to outright deflation."),
        ("Recession", "A broad and meaningful contraction in economic activity.", "Recessions usually pressure earnings and credit while prompting policy responses."),
        ("Soft Landing", "A slowdown that reduces inflation without a severe recession.", "The outcome can support earnings while allowing interest-rate pressure to ease."),
        ("Stagflation", "Weak growth combined with high inflation.", "It constrains policy choices and can pressure both margins and valuation."),
        ("Yield Curve", "The relationship between yields and maturities for comparable debt securities.", "Its level and shape reflect policy, growth, inflation, and term-premium expectations."),
        ("Yield Curve Inversion", "A condition in which shorter-term yields exceed longer-term yields.", "It has preceded many recessions but provides uncertain timing."),
        ("Federal Funds Rate", "The overnight U.S. interbank rate targeted by the Federal Reserve.", "It anchors short-term funding costs and influences broader financial conditions."),
        ("Quantitative Easing", "Central-bank asset purchases intended to add liquidity and lower longer-term yields.", "It can support financial conditions but its effects depend on context and expectations."),
        ("Quantitative Tightening", "Reduction of a central bank's securities holdings or balance-sheet support.", "It can withdraw liquidity and place upward pressure on term premiums."),
        ("Real Interest Rate", "An interest rate adjusted for expected or realized inflation.", "Real rates influence consumption, investment, currencies, and equity duration."),
        ("Credit Spread", "The yield difference between a risky debt instrument and a comparable benchmark.", "Widening spreads can signal rising default risk and tighter financial conditions."),
        ("Purchasing Managers' Index", "A diffusion index derived from business surveys, with 50 commonly separating expansion from contraction.", "PMIs are timely indicators of economic direction and corporate conditions."),
        ("Consensus Estimate", "The aggregated forecast of surveyed economists or analysts.", "Markets usually react to the difference between reported data and expectations."),
        ("Nowcast", "A model-based estimate of current economic conditions before complete official data are available.", "It updates faster than traditional forecasts but remains uncertain and revision-prone."),
    ),
    BEHAVIORAL_FINANCE: (
        ("Behavioral Finance", "Study of how cognitive and emotional biases affect financial decisions and markets.", "Recognizing predictable errors can improve process even when they cannot be eliminated."),
        ("Anchoring", "Overreliance on an initial number or reference point.", "Purchase price and old highs can distort a fresh assessment of value."),
        ("Confirmation Bias", "Preference for evidence that supports an existing belief.", "Actively seeking disconfirming evidence improves thesis quality."),
        ("Loss Aversion", "The tendency to experience losses more strongly than equivalent gains.", "It can cause premature profit-taking and reluctance to exit failed positions."),
        ("Disposition Effect", "The tendency to sell winners too early and hold losers too long.", "It can weaken risk-adjusted returns and tax efficiency."),
        ("Recency Bias", "Overweighting recent events when judging future probabilities.", "Recent performance may be mistaken for a durable regime."),
        ("Overconfidence", "Excessive belief in one's information, forecasts, or skill.", "It often leads to concentration, leverage, and unnecessary trading."),
        ("Herding", "Following the actions of a group instead of relying on independent analysis.", "Crowds can aggregate information but also create crowded trades."),
        ("Fear of Missing Out", "Anxiety-driven buying motivated by others' gains or rapidly rising prices.", "It encourages poor entries, oversized positions, and abandoned risk controls."),
        ("Panic Selling", "Urgent selling driven primarily by fear during a decline.", "It can lock in losses without evaluating liquidity needs or thesis changes."),
        ("Sunk Cost Fallacy", "Allowing past, unrecoverable costs to influence a current decision.", "Future risk and reward should matter more than the original purchase price."),
        ("Endowment Effect", "Valuing an asset more highly merely because it is owned.", "Owners may demand more evidence to sell than they required to buy."),
        ("Mental Accounting", "Treating money differently based on arbitrary labels or sources.", "It can hide the portfolio's true combined risk and opportunity cost."),
        ("Availability Bias", "Judging likelihood by how easily examples come to mind.", "Vivid news can overwhelm base rates and broader evidence."),
        ("Narrative Fallacy", "Constructing a persuasive story that overstates causal understanding.", "A coherent narrative should still be tested against data and alternatives."),
        ("Survivorship Bias", "Studying only investments or funds that survived while ignoring failures.", "It overstates historical performance and strategy reliability."),
        ("Hindsight Bias", "Seeing an outcome as more predictable after it occurred.", "Decision journals help separate process quality from outcome knowledge."),
        ("Base Rate", "The historical frequency of an outcome in a relevant reference class.", "Base rates provide a starting point before company-specific adjustments."),
        ("Reflexivity", "A feedback loop in which market perceptions influence fundamentals, which then influence perceptions.", "Prices can affect financing, confidence, and business outcomes rather than merely reflect them."),
        ("Crowded Trade", "A position held by many investors with similar reasons and exit triggers.", "Even a sound thesis can suffer when positioning unwinds abruptly."),
        ("Capitulation", "A burst of intense selling that reflects investors giving up on positions.", "It can occur near a low but is recognizable only imperfectly in real time."),
        ("Market Sentiment", "The prevailing attitude and risk appetite of market participants.", "Sentiment can drive valuation and positioning away from near-term fundamentals."),
    ),
}


_FORMULA_SPECS: tuple[tuple[str, str, str, str, str, str, str], ...] = (
    ("Market Capitalization Formula", MARKET_BASICS, "Equity market value based on the current share price.", "It converts a per-share quote into total public equity value.", "Market capitalization = Share price × Diluted shares outstanding", "At $40 per share and 250 million shares, market capitalization is $10 billion.", "Use a consistent diluted share count; market cap is not enterprise value."),
    ("Enterprise Value", VALUATION_FORMULAS, "The value attributed to a company's operating assets for all capital providers.", "It supports comparisons using pre-financing operating metrics.", "EV = Equity value + Debt + Preferred stock + Noncontrolling interest − Cash", "A $12B market cap plus $3B debt and $1B cash produces about $14B EV.", "Adjustments vary; restricted cash, leases, pensions, and investments require judgment."),
    ("Earnings per Share", FINANCIAL_STATEMENTS, "Net income attributable to common shareholders expressed per weighted-average diluted share.", "EPS connects company profit with each share and is central to P/E valuation.", "Diluted EPS = Common net income ÷ Diluted weighted-average shares", "$500M of common net income across 250M diluted shares equals $2.00 EPS.", "Buybacks, dilution, one-time items, and accounting choices can change EPS without equal operating change."),
    ("Price-to-Earnings Ratio", VALUATION_FORMULAS, "Share price relative to earnings per share.", "It shows how much investors pay for each unit of current or expected earnings.", "P/E = Share price ÷ EPS", "A $60 stock earning $3 per share trades at 20× earnings.", "P/E is not meaningful with negative earnings and must be paired with growth, quality, and cycle context."),
    ("Forward P/E", VALUATION_FORMULAS, "Share price relative to forecast earnings per share.", "It embeds the market's view against near-term earnings expectations.", "Forward P/E = Share price ÷ Forecast EPS", "A $60 stock with expected EPS of $4 trades at 15× forward earnings.", "Forecast error and differing estimate periods can make comparisons misleading."),
    ("Price-to-Sales Ratio", VALUATION_FORMULAS, "Equity value relative to revenue.", "It is usable when earnings are small or negative, but ignores cost structure.", "P/S = Market capitalization ÷ Revenue", "A $5B company with $1B revenue trades at 5× sales.", "Margins, dilution, capital intensity, and revenue quality determine whether the multiple is sensible."),
    ("Price-to-Book Ratio", VALUATION_FORMULAS, "Equity value relative to common shareholders' book value.", "It is often used for financial firms and asset-heavy businesses.", "P/B = Market capitalization ÷ Common book value", "A $12B market cap divided by $8B book value equals 1.5× book.", "Accounting book value may poorly represent intangible-heavy or impaired assets."),
    ("Enterprise Value to EBITDA", VALUATION_FORMULAS, "Enterprise value divided by EBITDA.", "It compares operating value before capital structure, tax, and noncash charges.", "EV/EBITDA = Enterprise value ÷ EBITDA", "$15B EV divided by $1.5B EBITDA equals 10×.", "EBITDA is not cash flow and the multiple can hide capital expenditure and working-capital needs."),
    ("PEG Ratio", VALUATION_FORMULAS, "A P/E ratio scaled by an earnings-growth rate.", "It provides a rough bridge between valuation and growth.", "PEG = P/E ÷ EPS growth rate expressed as a whole percentage", "A 24× P/E with 12% growth gives a PEG of 2.0.", "Growth definitions, cyclicality, and the arbitrary scaling make PEG only a screening aid."),
    ("Dividend Yield", VALUATION_FORMULAS, "Expected annual dividend per share relative to share price.", "It measures indicated cash income before taxes and reinvestment.", "Dividend yield = Annual dividend per share ÷ Share price", "$2 annual dividends on a $50 share equal a 4% yield.", "A high yield may signal a pending cut; use sustainable forward dividends."),
    ("Dividend Payout Ratio", VALUATION_FORMULAS, "The share of earnings distributed as dividends.", "It helps assess dividend coverage and retained reinvestment capacity.", "Payout ratio = Common dividends ÷ Common net income", "$300M dividends on $500M common earnings equals 60%.", "For some sectors, free-cash-flow payout or distributable cash flow is more informative."),
    ("Free Cash Flow", FINANCIAL_STATEMENTS, "Cash generated after operating needs and capital expenditures.", "It is cash potentially available for debt reduction, distributions, acquisitions, or reinvestment.", "FCF = Cash flow from operations − Capital expenditures", "$800M operating cash flow less $300M capex equals $500M FCF.", "Classifying capex, stock compensation, acquisitions, and working-capital swings requires judgment."),
    ("Free Cash Flow Yield", VALUATION_FORMULAS, "Free cash flow relative to equity value or enterprise value, depending on the cash-flow definition.", "It translates cash generation into a valuation yield.", "Equity FCF yield = Free cash flow to equity ÷ Market capitalization", "$500M FCF on a $10B market cap equals 5%.", "Keep numerator and denominator consistent and normalize temporary cash-flow swings."),
    ("Gross Margin", FINANCIAL_STATEMENTS, "Gross profit expressed as a percentage of revenue.", "It reflects product economics, pricing, input costs, and mix.", "Gross margin = (Revenue − Cost of goods sold) ÷ Revenue", "$400M gross profit on $1B revenue equals 40%.", "Classification policies and business mix can limit comparisons."),
    ("Operating Margin", FINANCIAL_STATEMENTS, "Operating income expressed as a percentage of revenue.", "It shows profit from operations before financing and tax.", "Operating margin = Operating income ÷ Revenue", "$150M operating income on $1B revenue equals 15%.", "Adjust consistently for restructuring, stock compensation, and unusual items."),
    ("Net Margin", FINANCIAL_STATEMENTS, "Net income expressed as a percentage of revenue.", "It captures the final accounting profitability available to owners.", "Net margin = Net income ÷ Revenue", "$80M net income on $1B revenue equals 8%.", "Taxes, financing, gains, and one-time items can obscure operating trends."),
    ("Return on Equity", RISK_PERFORMANCE, "Net income generated relative to average common equity.", "It measures owner-capital productivity but can be boosted by leverage.", "ROE = Common net income ÷ Average common equity", "$1B profit on $5B average equity equals 20% ROE.", "Buybacks, write-downs, and high debt can shrink equity and inflate ROE."),
    ("Return on Assets", RISK_PERFORMANCE, "Net income generated relative to average total assets.", "It helps compare asset productivity within similar industries.", "ROA = Net income ÷ Average total assets", "$500M profit on $10B assets equals 5% ROA.", "Asset intensity and accounting values differ widely across industries."),
    ("Return on Invested Capital", RISK_PERFORMANCE, "After-tax operating profit relative to capital invested in operations.", "ROIC versus cost of capital indicates whether growth creates economic value.", "ROIC = NOPAT ÷ Average invested capital", "$600M NOPAT on $4B invested capital equals 15% ROIC.", "NOPAT and invested-capital adjustments must be consistent across companies and time."),
    ("Current Ratio", FINANCIAL_STATEMENTS, "Current assets relative to current liabilities.", "It is a basic measure of near-term balance-sheet coverage.", "Current ratio = Current assets ÷ Current liabilities", "$2B current assets divided by $1B current liabilities equals 2.0×.", "Inventory quality, credit lines, seasonality, and cash conversion matter beyond the ratio."),
    ("Quick Ratio", FINANCIAL_STATEMENTS, "Liquid current assets relative to current liabilities.", "It excludes inventory to provide a stricter short-term liquidity view.", "Quick ratio = (Cash + Marketable securities + Receivables) ÷ Current liabilities", "$900M quick assets divided by $600M liabilities equals 1.5×.", "Receivable quality and access to funding still matter."),
    ("Debt-to-Equity Ratio", RISK_PERFORMANCE, "Debt relative to shareholders' equity.", "It gives a simple view of balance-sheet leverage.", "Debt-to-equity = Total debt ÷ Shareholders' equity", "$3B debt divided by $2B equity equals 1.5×.", "Negative or unusually small book equity makes the ratio unreliable."),
    ("Interest Coverage Ratio", RISK_PERFORMANCE, "Operating earnings available relative to interest expense.", "It indicates the cushion for servicing debt.", "Interest coverage = EBIT ÷ Net interest expense", "$600M EBIT divided by $100M interest equals 6× coverage.", "Cyclical earnings, floating rates, maturities, and cash balances affect true credit capacity."),
    ("Compound Annual Growth Rate", FUNDAMENTAL_ANALYSIS, "The constant annual rate that links a beginning value to an ending value over multiple years.", "It summarizes multi-period growth in one comparable number.", "CAGR = (Ending value ÷ Beginning value)^(1 ÷ Years) − 1", "Growth from 100 to 161.05 in five years equals a 10% CAGR.", "CAGR hides volatility and the path between endpoints."),
    ("Total Return", RISK_PERFORMANCE, "The combined price change and distributions earned over a period.", "It is the correct basis for comparing investments that pay different income.", "Total return = (Ending value − Beginning value + Distributions) ÷ Beginning value", "A move from $100 to $108 plus a $2 dividend produces a 10% total return.", "Use adjusted prices and consistent treatment of reinvestment and taxes."),
    ("Beta", RISK_PERFORMANCE, "The estimated sensitivity of a security's returns to benchmark returns.", "It summarizes historical market exposure for portfolio and cost-of-equity work.", "Beta = Covariance(asset, market) ÷ Variance(market)", "A beta of 1.3 implies an estimated 1.3% move for each 1% benchmark move, on average.", "Beta depends on benchmark, window, frequency, leverage, and changing regimes."),
    ("Alpha", RISK_PERFORMANCE, "Return beyond that implied by a selected risk model or benchmark.", "It separates skill or unexplained performance from systematic exposure.", "Simple alpha = Portfolio return − Expected return from the chosen model", "A 12% return against a model expectation of 9% implies 3% alpha.", "Alpha is model-dependent and can reflect omitted risks, luck, or bad benchmarking."),
    ("Sharpe Ratio", RISK_PERFORMANCE, "Excess return per unit of total return volatility.", "It compares reward with variability across strategies.", "Sharpe = (Portfolio return − Risk-free rate) ÷ Return standard deviation", "An 8% excess return with 16% volatility gives a Sharpe ratio of 0.5.", "It treats upside and downside volatility equally and can understate tail risk."),
    ("Sortino Ratio", RISK_PERFORMANCE, "Excess return per unit of downside deviation.", "It focuses the risk penalty on returns below a selected target.", "Sortino = (Portfolio return − Target return) ÷ Downside deviation", "A 6% excess return with 8% downside deviation gives 0.75.", "Results depend on the target, data frequency, and limited tail observations."),
    ("Maximum Drawdown", RISK_PERFORMANCE, "The largest peak-to-trough percentage decline in a return series.", "It conveys historical loss severity and recovery burden.", "Maximum drawdown = Minimum[(Value ÷ Prior peak) − 1]", "A fall from 120 to 84 is a 30% drawdown.", "It describes one historical path and does not bound future losses."),
    ("Annualized Volatility", RISK_PERFORMANCE, "Return standard deviation scaled to a one-year horizon.", "It enables rough comparison across assets and sampling frequencies.", "Annualized volatility ≈ Periodic standard deviation × √Periods per year", "A 1% daily standard deviation gives about 15.9% annualized volatility using 252 days.", "Square-root scaling assumes stable, weakly dependent returns and can fail in crises."),
    ("Present Value", VALUATION_FORMULAS, "The current value of a future cash flow discounted for time and risk.", "It is the core building block of discounted valuation.", "PV = Future cash flow ÷ (1 + Discount rate)^Periods", "$110 received in one year discounted at 10% has a $100 present value.", "The correct discount rate must match the cash flow's risk and currency."),
    ("Weighted Average Cost of Capital", VALUATION_FORMULAS, "The blended required return of debt and equity capital weighted by market values.", "It is commonly used to discount unlevered free cash flow.", "WACC = E/(D+E)×Cost of equity + D/(D+E)×After-tax cost of debt", "With 80% equity at 10% and 20% debt at 4% after tax, WACC is 8.8%.", "Capital structure, beta, tax, country risk, and cyclicality make WACC uncertain."),
    ("Gordon Growth Terminal Value", VALUATION_FORMULAS, "A terminal-value method assuming cash flow grows perpetually at a constant rate.", "It converts the post-forecast cash-flow stream into one value.", "Terminal value = Next-period cash flow ÷ (Discount rate − Perpetual growth)", "$105 cash flow with 8% discount and 3% growth gives $2,100 terminal value.", "Growth must remain below the discount rate and be sustainable for the economy and business."),
    ("Simple Moving Average", TECHNICAL_INDICATORS, "The arithmetic mean of prices over a fixed rolling window.", "It smooths noise and provides a lagging trend reference.", "SMA(n) = Sum of last n prices ÷ n", "Closing prices 10, 11, 12, 13, and 14 produce a five-period SMA of 12.", "Window choice changes responsiveness; moving averages do not predict turning points."),
    ("Exponential Moving Average", TECHNICAL_INDICATORS, "A moving average that gives greater weight to recent observations.", "It reacts faster than a same-length simple moving average.", "EMA today = Price today×k + EMA prior×(1−k), where k = 2/(n+1)", "A 10-period EMA uses a smoothing factor of 2/11, or about 18.18%.", "Faster response also increases sensitivity to noise."),
    ("Relative Strength Index", TECHNICAL_INDICATORS, "A bounded momentum oscillator comparing average gains with average losses.", "It helps describe momentum regime, extension, and divergence.", "RSI = 100 − 100/(1 + Average gain ÷ Average loss)", "An average gain twice the average loss produces an RSI near 66.7.", "Overbought is not automatically bearish and oversold is not automatically bullish."),
    ("Moving Average Convergence Divergence", TECHNICAL_INDICATORS, "A momentum indicator based on the difference between fast and slow exponential moving averages.", "Crossovers and histogram changes help describe trend momentum.", "MACD = Fast EMA − Slow EMA; Histogram = MACD − Signal EMA", "With a fast EMA of 105 and slow EMA of 100, MACD is +5 before the signal comparison.", "It is lagging and can whipsaw in sideways markets."),
)


_FORMULA_VARIABLES: dict[str, str] = {
    "Market Capitalization Formula": "Share price is the current price per common share; diluted shares outstanding includes the expected effect of dilutive awards and securities.",
    "Enterprise Value": "Equity value is common market capitalization; debt includes interest-bearing obligations; cash is excess cash and equivalents; preferred stock and noncontrolling interest are non-common claims.",
    "Earnings per Share": "Common net income is profit attributable to common owners; diluted weighted-average shares reflects the time-weighted share count plus dilutive instruments.",
    "Price-to-Earnings Ratio": "Share price and EPS must refer to the same share class; EPS may be trailing, forward, GAAP, or adjusted and must be labeled consistently.",
    "Forward P/E": "Share price is today's quote; forecast EPS is the expected per-share profit for a clearly identified future period.",
    "Price-to-Sales Ratio": "Market capitalization is common equity value; revenue is company sales over a consistent trailing or forecast period.",
    "Price-to-Book Ratio": "Market capitalization is common equity value; common book value is assets minus liabilities and senior equity claims.",
    "Enterprise Value to EBITDA": "Enterprise value represents all operating capital claims; EBITDA is earnings before interest, tax, depreciation, and amortization for the matching period.",
    "PEG Ratio": "P/E is the selected earnings multiple; EPS growth is entered as a whole percentage, so 12% is entered as 12 rather than 0.12.",
    "Dividend Yield": "Annual dividend per share is the indicated recurring distribution over one year; share price is the current price.",
    "Dividend Payout Ratio": "Common dividends are distributions declared for common owners; common net income is profit attributable to those owners for the same period.",
    "Free Cash Flow": "Cash flow from operations is operating cash generated; capital expenditures are cash purchases of property, equipment, and other long-lived operating assets.",
    "Free Cash Flow Yield": "Free cash flow to equity is cash available to common owners; market capitalization is the value of common equity.",
    "Gross Margin": "Revenue is recognized sales; cost of goods sold is the direct cost assigned to those sales.",
    "Operating Margin": "Operating income is profit before financing and income tax; revenue is sales for the same period.",
    "Net Margin": "Net income is bottom-line accounting profit; revenue is sales for the same period.",
    "Return on Equity": "Common net income is profit attributable to common owners; average common equity is normally the mean of beginning and ending common equity.",
    "Return on Assets": "Net income is bottom-line profit; average total assets is normally the mean of beginning and ending assets.",
    "Return on Invested Capital": "NOPAT is net operating profit after tax; invested capital is the operating capital supplied by debt and equity holders, averaged when practical.",
    "Current Ratio": "Current assets are expected to convert to cash within the operating cycle or one year; current liabilities are obligations due over the same horizon.",
    "Quick Ratio": "Quick assets are cash, marketable securities, and collectible receivables; current liabilities are near-term obligations.",
    "Debt-to-Equity Ratio": "Total debt is interest-bearing borrowing; shareholders' equity is the accounting residual attributable to owners.",
    "Interest Coverage Ratio": "EBIT is earnings before interest and tax; net interest expense is interest cost after interest income when that convention is used.",
    "Compound Annual Growth Rate": "Beginning and ending values use the same metric and units; years is the number of compounding intervals between them.",
    "Total Return": "Beginning and ending values refer to the investment value; distributions include cash dividends or other payouts received during the period.",
    "Beta": "Covariance measures joint asset and benchmark returns; variance measures benchmark-return dispersion over the same observations.",
    "Alpha": "Portfolio return is the observed result; expected return is the result implied by the chosen benchmark or factor model.",
    "Sharpe Ratio": "Portfolio return and risk-free rate use the same horizon; standard deviation is the volatility of portfolio returns over that horizon.",
    "Sortino Ratio": "Portfolio return and target return use the same horizon; downside deviation measures returns falling below the target.",
    "Maximum Drawdown": "Value is the portfolio or price index at each observation; prior peak is the highest value observed before that point.",
    "Annualized Volatility": "Periodic standard deviation uses returns at one frequency; periods per year is commonly 252 for daily or 12 for monthly observations.",
    "Present Value": "Future cash flow is the amount received later; discount rate is the required return per period; periods is the number of matching compounding intervals.",
    "Weighted Average Cost of Capital": "E and D are market values of equity and debt; each cost is the required return for that capital source; debt cost is reduced by the applicable tax shield.",
    "Gordon Growth Terminal Value": "Next-period cash flow is the first cash flow after the forecast; discount rate is the required return; perpetual growth is the sustainable long-run growth rate.",
    "Simple Moving Average": "n is the number of observations in the rolling window; prices are normally closes sampled at a consistent interval.",
    "Exponential Moving Average": "n is the selected lookback; k is the smoothing factor; EMA prior is the preceding period's exponential average.",
    "Relative Strength Index": "Average gain and average loss are smoothed positive and negative price changes over the chosen lookback, commonly 14 periods.",
    "Moving Average Convergence Divergence": "Fast and slow EMA are commonly 12 and 26 periods; the signal EMA is commonly a 9-period EMA of the MACD line.",
}


_EVENT_SPECS: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("FOMC Decision", "Federal Reserve", "Target-rate decision and policy statement, normally eight scheduled times per year.", "Compare the decision, statement, projections, and press conference with what rates markets expected.", "Front-end Treasury yields, the dollar, valuation multiples, banks, housing, and broad risk appetite.", "A nominally unchanged rate can still be hawkish or dovish; market positioning often dominates the first reaction."),
    ("FOMC Minutes", "Federal Reserve", "Detailed account of a prior policy meeting, normally released with a lag.", "Look for the range of views, risk balance, and conditions members attached to future action.", "Rates and currencies first, with equity effects through discount rates and growth expectations.", "The minutes describe an older meeting and may be overtaken by newer data or speeches."),
    ("CPI Release", "Bureau of Labor Statistics", "Monthly consumer-price inflation for a basket of goods and services.", "Compare headline and core monthly rates, breadth, shelter, services, revisions, and consensus.", "Treasury yields, policy expectations, the dollar, rate-sensitive growth stocks, housing, and consumer margins.", "One month can be noisy; base effects and seasonal adjustment can distort annual comparisons."),
    ("PPI Release", "Bureau of Labor Statistics", "Monthly prices received by domestic producers across stages of production.", "Compare final-demand and underlying components with expectations and possible pass-through to consumers.", "Inflation expectations, margins, rates, industrial companies, and pricing-power narratives.", "PPI composition differs from CPI and does not mechanically predict consumer inflation."),
    ("PCE Inflation", "Bureau of Economic Analysis", "Monthly personal-consumption inflation using weights that adjust with consumer behavior.", "Core PCE and its monthly pace are central to Federal Reserve analysis; compare with consensus and revisions.", "Policy expectations, bond yields, currencies, and equity valuation through real-rate expectations.", "The release contains revisions and may largely reflect already published CPI and PPI components."),
    ("Jobs Report", "Bureau of Labor Statistics", "Monthly employment situation covering payrolls, unemployment, wages, hours, and participation.", "Read payrolls with revisions, household employment, participation, wage growth, and workweek versus expectations.", "Growth expectations, policy pricing, rates, consumer sectors, staffing, and cyclicals.", "Payroll and household surveys can diverge; weather, strikes, and seasonal factors create noise."),
    ("JOLTS Report", "Bureau of Labor Statistics", "Monthly estimates of job openings, hires, quits, and separations.", "Openings and quits help assess labor demand and worker confidence relative to labor supply.", "Wage-pressure expectations, policy pricing, staffing firms, and cyclical sentiment.", "The data are lagged, revised, and based on a survey with meaningful sampling uncertainty."),
    ("Initial Jobless Claims", "U.S. Department of Labor", "Weekly count of new unemployment-insurance claims.", "Use the trend and continuing claims rather than overreacting to one holiday-distorted week.", "Near-term labor and recession expectations, rates, and cyclical equities.", "Eligibility rules, seasonality, disasters, and reporting backlogs can distort the series."),
    ("GDP Report", "Bureau of Economic Analysis", "Quarterly estimate of real economic output, released in advance, second, and third estimates.", "Compare growth composition, price indexes, inventories, trade, and domestic final demand with expectations.", "Cyclicals, yields, policy expectations, earnings forecasts, and recession probabilities.", "Headline GDP can be boosted by volatile inventories or trade while domestic demand weakens."),
    ("Retail Sales", "U.S. Census Bureau", "Monthly estimate of sales at retail and food-service businesses.", "Compare the control group, revisions, price effects, and category breadth with expectations.", "Consumer discretionary and staples, GDP tracking, rates, card issuers, and logistics.", "The release is nominal, excludes most services, and can be distorted by gasoline and autos."),
    ("Durable Goods Report", "U.S. Census Bureau", "Monthly new orders for long-lasting manufactured goods.", "Separate volatile aircraft and defense orders and inspect core capital-goods orders and shipments.", "Industrials, transports, business-investment expectations, and GDP tracking.", "Large aircraft orders make the headline exceptionally volatile."),
    ("Industrial Production", "Federal Reserve", "Monthly output of manufacturing, mining, and utilities.", "Compare manufacturing breadth, capacity utilization, revisions, and weather-sensitive utilities.", "Industrials, commodities, margins, and cyclical growth expectations.", "Utilities and mining can obscure the manufacturing signal."),
    ("ISM Manufacturing PMI", "Institute for Supply Management", "Monthly survey diffusion index for U.S. manufacturing activity.", "Read new orders, production, employment, prices, and supplier deliveries around the 50 level.", "Industrials, materials, rates, earnings expectations, and broader risk appetite.", "A diffusion index measures direction and breadth, not the percentage change in output."),
    ("ISM Services PMI", "Institute for Supply Management", "Monthly survey diffusion index for U.S. services activity.", "Compare business activity, new orders, employment, and prices with consensus and prior trends.", "Rates, domestic cyclicals, labor demand, and inflation-sensitive sectors.", "Survey composition and the 50 threshold do not map directly to GDP growth."),
    ("Consumer Confidence", "The Conference Board", "Monthly survey of household views on current conditions and expectations.", "Separate present conditions from expectations and compare labor perceptions with spending data.", "Consumer sectors, recession views, housing, and discretionary demand.", "Attitudes can respond to politics and gasoline prices without equal spending changes."),
    ("University of Michigan Sentiment", "University of Michigan", "Preliminary and final monthly survey of consumer sentiment and inflation expectations.", "Markets focus on changes in one-year and long-run inflation expectations as well as sentiment.", "Rates, policy expectations, consumer sectors, and inflation narratives.", "The sample is smaller than hard spending data and preliminary figures can be revised."),
    ("Housing Starts", "U.S. Census Bureau and HUD", "Monthly estimate of new residential construction starts and permits.", "Permits lead starts; inspect single-family versus multifamily activity and regional volatility.", "Homebuilders, building products, mortgage sensitivity, banks, and cyclical growth.", "Weather and small regional samples create large monthly swings."),
    ("Existing Home Sales", "National Association of Realtors", "Monthly count of completed sales of previously owned homes.", "Inventory, months of supply, prices, and mortgage-rate sensitivity matter with the headline.", "Housing-linked equities, brokers, lenders, renovation, and consumer durables.", "Closings lag purchase agreements and the series is not an official government release."),
    ("New Home Sales", "U.S. Census Bureau and HUD", "Monthly annualized estimate of new single-family home sales.", "Compare supply, price mix, revisions, and regional breadth with mortgage-rate conditions.", "Homebuilders, building materials, mortgage finance, and housing-led growth.", "The estimate has a wide confidence interval and is frequently revised."),
    ("Trade Balance", "Bureau of Economic Analysis and U.S. Census Bureau", "Monthly difference between exports and imports of goods and services.", "Inspect real versus nominal flows, petroleum, capital goods, and country or product concentration.", "GDP tracking, currencies, exporters, transport, and trade-policy narratives.", "A narrower deficit can reflect weaker domestic demand rather than stronger competitiveness."),
    ("Beige Book", "Federal Reserve", "Qualitative summary of economic conditions across Federal Reserve districts, published before policy meetings.", "Look for changes in activity, labor availability, wages, prices, credit, and regional breadth.", "Policy narratives, banks, regional activity, and confirmation of survey trends.", "It is anecdotal and descriptive, not a statistically representative forecast."),
)


_ALIASES: dict[str, tuple[str, ...]] = {
    "Advance-Decline Line": ("A/D Line",),
    "American Depositary Receipt": ("ADR",),
    "Average True Range": ("ATR",),
    "Business Development Company": ("BDC",),
    "Compound Annual Growth Rate": ("CAGR",),
    "Consumer Price Index": ("CPI",),
    "Debt-to-Equity Ratio": ("D/E",),
    "Discounted Cash Flow": ("DCF",),
    "Earnings Before Interest and Taxes": ("EBIT",),
    "Earnings per Share": ("EPS", "Diluted EPS"),
    "Enterprise Value": ("EV",),
    "Enterprise Value to EBITDA": ("EV/EBITDA",),
    "Exchange-Traded Fund": ("ETF",),
    "Federal Funds Rate": ("Fed Funds Rate",),
    "Fear of Missing Out": ("FOMO",),
    "FOMC Decision": ("Fed Decision", "Federal Reserve Decision"),
    "FOMC Minutes": ("Fed Minutes",),
    "Free Cash Flow": ("FCF",),
    "Free Cash Flow Yield": ("FCF Yield",),
    "Good-Til-Canceled": ("GTC",),
    "Immediate-or-Cancel": ("IOC",),
    "Initial Public Offering": ("IPO",),
    "Institute for Supply Management": ("ISM",),
    "JOLTS Report": ("Job Openings", "JOLTS"),
    "Market Capitalization": ("Market Cap",),
    "Market Capitalization Formula": ("Market Cap Formula",),
    "Master Limited Partnership": ("MLP",),
    "Maximum Drawdown": ("Max Drawdown", "MDD"),
    "Moving Average Convergence Divergence": ("MACD",),
    "Net Revenue Retention": ("NRR",),
    "Noncontrolling Interest": ("Minority Interest",),
    "On-Balance Volume": ("OBV",),
    "Payment for Order Flow": ("PFOF",),
    "Personal Consumption Expenditures": ("PCE",),
    "Price-to-Book Ratio": ("P/B", "Price to Book"),
    "Price-to-Earnings Ratio": ("P/E", "PE Ratio", "Price Earnings Ratio"),
    "Price-to-Sales Ratio": ("P/S", "Price to Sales"),
    "Purchasing Managers' Index": ("PMI",),
    "Quantitative Easing": ("QE",),
    "Quantitative Tightening": ("QT",),
    "Real Estate Investment Trust": ("REIT",),
    "Relative Strength Index": ("RSI",),
    "Return on Assets": ("ROA",),
    "Return on Equity": ("ROE",),
    "Return on Invested Capital": ("ROIC",),
    "Simple Moving Average": ("SMA", "Moving Average"),
    "Sum-of-the-Parts Valuation": ("SOTP",),
    "Total Addressable Market": ("TAM",),
    "Value at Risk": ("VaR",),
    "Volume-Weighted Average Price": ("VWAP",),
    "Weighted Average Cost of Capital": ("WACC",),
}


_RELATED: dict[str, tuple[str, ...]] = {
    "Ask": ("Bid", "Bid-Ask Spread", "Market Order"),
    "Bid": ("Ask", "Bid-Ask Spread", "Limit Order"),
    "Bid-Ask Spread": ("Bid", "Ask", "Liquidity", "Slippage"),
    "Market Capitalization": ("Shares Outstanding", "Float", "Enterprise Value"),
    "Enterprise Value": ("Market Capitalization", "Enterprise Value to EBITDA", "Discounted Cash Flow"),
    "Earnings per Share": ("Net Income", "Price-to-Earnings Ratio", "Stock-Based Compensation"),
    "Price-to-Earnings Ratio": ("Forward P/E", "Earnings per Share", "PEG Ratio"),
    "Free Cash Flow": ("Cash Flow Statement", "Capital Expenditure", "Free Cash Flow Yield"),
    "Return on Invested Capital": ("Weighted Average Cost of Capital", "Economic Moat", "Operating Margin"),
    "Discounted Cash Flow": ("Present Value", "Weighted Average Cost of Capital", "Terminal Value"),
    "Relative Strength Index": ("Momentum", "Divergence", "Moving Average Convergence Divergence"),
    "Moving Average Convergence Divergence": ("Exponential Moving Average", "Momentum", "Divergence"),
    "Call Option": ("Put Option", "Strike Price", "Delta", "Implied Volatility"),
    "Put Option": ("Call Option", "Protective Put", "Delta", "Implied Volatility"),
    "Implied Volatility": ("Historical Volatility", "Vega", "Option Premium"),
    "FOMC Decision": ("Federal Funds Rate", "Monetary Policy", "FOMC Minutes"),
    "CPI Release": ("Inflation", "PCE Inflation", "PPI Release"),
    "Jobs Report": ("JOLTS Report", "Initial Jobless Claims", "Recession"),
    "Confirmation Bias": ("Investment Thesis", "Overconfidence", "Base Rate"),
    "Diversification": ("Correlation", "Asset Allocation", "Concentration"),
}


def _build_entries() -> tuple[DictionaryEntry, ...]:
    entries: list[DictionaryEntry] = []
    formula_terms = {spec[0] for spec in _FORMULA_SPECS}
    for category, rows in _CORE_ROWS.items():
        for term, definition, why_it_matters in rows:
            # Formula entries replace same-name compact rows with expanded records.
            if term in formula_terms:
                continue
            entries.append(
                _entry(
                    term,
                    category,
                    definition,
                    why_it_matters,
                    aliases=_ALIASES.get(term, ()),
                    related=_RELATED.get(term, ()),
                )
            )

    for term, category, definition, why_it_matters, formula, example, limitation in _FORMULA_SPECS:
        entries.append(
            _entry(
                term,
                category,
                definition,
                why_it_matters,
                aliases=_ALIASES.get(term, ()),
                related=_RELATED.get(term, ()),
                keywords=("formula", "calculation", "ratio"),
                sections=(
                    _section("Formula", formula),
                    _section("Variables", _FORMULA_VARIABLES[term]),
                    _section("Worked example", example),
                    _section("Interpretation and limitation", limitation),
                ),
            )
        )

    for term, source, measurement, interpretation, channels, caution in _EVENT_SPECS:
        entries.append(
            _entry(
                term,
                MACRO_EVENTS,
                measurement,
                "Scheduled releases matter mainly through the surprise versus expectations and the change in the expected economic path.",
                aliases=_ALIASES.get(term, ()),
                related=_RELATED.get(term, ()),
                keywords=("economic calendar", "release", "actual", "consensus", "prior", source),
                sections=(
                    _section("Publisher and cadence", source),
                    _section("How to read it", interpretation),
                    _section("Typical market channels", channels),
                    _section("Caution", caution),
                ),
            )
        )

    for pattern in CHART_PATTERN_CATALOG:
        entries.append(
            _entry(
                pattern.name,
                CHART_PATTERNS,
                pattern.recognition,
                f"This {pattern.bias.casefold()} {pattern.family.casefold()} formation provides a structured way to define confirmation and invalidation.",
                aliases=pattern.aliases,
                keywords=("chart pattern", pattern.family, pattern.bias, "breakout", "technical analysis"),
                sections=(
                    _section("Confirmation", pattern.confirmation),
                    _section("Invalidation", pattern.invalidation),
                    _section("Measured target", pattern.target),
                    _section("Practical caution", "Treat the diagram as a schematic. Confirm the real price structure, timeframe, liquidity, and volume rather than matching a shape mechanically."),
                ),
                chart_pattern_id=pattern.pattern_id,
            )
        )

    by_id = {entry.entry_id: entry for entry in entries}
    # Retain only valid cross-references. Validation tests still guard against
    # accidental broken references in the published catalog.
    entries = [
        replace(entry, related_entry_ids=tuple(item for item in entry.related_entry_ids if item in by_id and item != entry.entry_id))
        for entry in entries
    ]
    return tuple(sorted(entries, key=lambda entry: (entry.term.casefold(), entry.term)))


DICTIONARY_ENTRIES = _build_entries()
DICTIONARY_ENTRY_BY_ID = {entry.entry_id: entry for entry in DICTIONARY_ENTRIES}


def get_dictionary_entry(entry_id: str) -> DictionaryEntry | None:
    return DICTIONARY_ENTRY_BY_ID.get(str(entry_id or "").strip().casefold())


def _search_blob(entry: DictionaryEntry) -> str:
    values = [
        entry.term,
        *entry.aliases,
        entry.category,
        entry.definition,
        entry.why_it_matters,
        *entry.keywords,
    ]
    for section in entry.sections:
        values.extend((section.title, section.body))
    return " ".join(str(value) for value in values).casefold()


def search_dictionary_entries(query: str = "", category: str | None = None) -> tuple[DictionaryEntry, ...]:
    normalized_query = " ".join(str(query or "").casefold().split())
    selected_category = str(category or "").strip()
    candidates = [
        entry
        for entry in DICTIONARY_ENTRIES
        if not selected_category or selected_category == "All categories" or entry.category == selected_category
    ]
    if not normalized_query:
        return tuple(candidates)

    ranked: list[tuple[int, str, DictionaryEntry]] = []
    query_tokens = tuple(normalized_query.split())
    for entry in candidates:
        term = entry.term.casefold()
        aliases = tuple(alias.casefold() for alias in entry.aliases)
        keywords = tuple(keyword.casefold() for keyword in entry.keywords)
        blob = _search_blob(entry)
        if term == normalized_query:
            rank = 0
        elif term.startswith(normalized_query):
            rank = 10
        elif normalized_query in aliases:
            rank = 20
        elif any(alias.startswith(normalized_query) for alias in aliases):
            rank = 25
        elif normalized_query in keywords or any(keyword.startswith(normalized_query) for keyword in keywords):
            rank = 30
        elif normalized_query in blob:
            rank = 40
        elif all(token in blob for token in query_tokens):
            rank = 50
        else:
            continue
        ranked.append((rank, term, entry))
    ranked.sort(key=lambda item: (item[0], item[1], item[2].term))
    return tuple(item[2] for item in ranked)


__all__ = [
    "DICTIONARY_CATEGORIES",
    "DICTIONARY_ENTRIES",
    "DICTIONARY_ENTRY_BY_ID",
    "DictionaryEntry",
    "DictionarySection",
    "get_dictionary_entry",
    "search_dictionary_entries",
]
