from __future__ import annotations

import datetime as dt
import os
import threading
import time
from typing import Any

from ..cache import CacheManager
from ..dependencies import pd, requests


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"

SEC_TICKERS_TTL_SECONDS = 24 * 60 * 60
SEC_FACTS_TTL_SECONDS = 6 * 60 * 60
SEC_SUBMISSIONS_TTL_SECONDS = 15 * 60
SEC_STALE_FALLBACK_SECONDS = 7 * 24 * 60 * 60
SEC_REQUEST_INTERVAL_SECONDS = 0.2
SEC_REQUEST_TIMEOUT_SECONDS = 15
SEC_MAX_ATTEMPTS = 3

_DEFAULT_USER_AGENT = (
    "BudgetTerminal/0.911 "
    "(SEC data integration; contact: maintainers-at-budget-terminal.invalid)"
)

_ANNUAL_FORMS = {"10-K", "10-K/A"}
_QUARTERLY_FORMS = {"10-Q", "10-Q/A"}
_FILING_FORM_PREFIXES = ("10-K", "10-Q", "8-K")


_METRIC_SPECS: dict[str, dict[str, Any]] = {
    "revenue": {
        "row": "Total Revenue",
        "family": "financials",
        "kind": "flow",
        "units": ("USD",),
        "tags": (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "SalesRevenueGoodsNet",
        ),
    },
    "gross_profit": {
        "row": "Gross Profit",
        "family": "financials",
        "kind": "flow",
        "units": ("USD",),
        "tags": ("GrossProfit",),
    },
    "operating_income": {
        "row": "Operating Income",
        "family": "financials",
        "kind": "flow",
        "units": ("USD",),
        "tags": ("OperatingIncomeLoss", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"),
    },
    "operating_expense": {
        "row": "Operating Expense",
        "family": "financials",
        "kind": "flow",
        "units": ("USD",),
        "tags": ("OperatingExpenses", "OperatingCostsAndExpenses"),
    },
    "net_income": {
        "row": "Net Income",
        "family": "financials",
        "kind": "flow",
        "units": ("USD",),
        "tags": ("NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"),
    },
    "diluted_eps": {
        "row": "Diluted EPS",
        "family": "financials",
        "kind": "flow",
        "units": ("USD/shares", "USD / shares"),
        "tags": ("EarningsPerShareDiluted",),
    },
    "diluted_shares": {
        "row": "Diluted Average Shares",
        "family": "financials",
        "kind": "flow",
        "units": ("shares",),
        "tags": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    },
    "operating_cash_flow": {
        "row": "Operating Cash Flow",
        "family": "cashflow",
        "kind": "flow",
        "units": ("USD",),
        "tags": ("NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    },
    "capital_expenditure": {
        "row": "Capital Expenditure",
        "family": "cashflow",
        "kind": "flow",
        "units": ("USD",),
        "tags": (
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsForAdditionsToPropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
        ),
        "absolute": True,
    },
    "cash": {
        "row": "Cash Cash Equivalents And Short Term Investments",
        "family": "balance_sheet",
        "kind": "instant",
        "units": ("USD",),
        "tags": (
            "CashCashEquivalentsAndShortTermInvestments",
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ),
    },
    "total_debt": {
        "row": "Total Debt",
        "family": "balance_sheet",
        "kind": "instant",
        "units": ("USD",),
        "tags": (
            "DebtAndFinanceLeaseObligations",
            "LongTermDebtAndFinanceLeaseObligations",
            "LongTermDebt",
        ),
    },
    "total_assets": {
        "row": "Total Assets",
        "family": "balance_sheet",
        "kind": "instant",
        "units": ("USD",),
        "tags": ("Assets",),
    },
    "total_liabilities": {
        "row": "Total Liabilities",
        "family": "balance_sheet",
        "kind": "instant",
        "units": ("USD",),
        "tags": ("Liabilities",),
    },
    "shareholder_equity": {
        "row": "Stockholders Equity",
        "family": "balance_sheet",
        "kind": "instant",
        "units": ("USD",),
        "tags": ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
    },
    "current_assets": {
        "row": "Current Assets",
        "family": "balance_sheet",
        "kind": "instant",
        "units": ("USD",),
        "tags": ("AssetsCurrent",),
    },
    "current_liabilities": {
        "row": "Current Liabilities",
        "family": "balance_sheet",
        "kind": "instant",
        "units": ("USD",),
        "tags": ("LiabilitiesCurrent",),
    },
    "shares_outstanding": {
        "row": "Common Stock Shares Outstanding",
        "family": "balance_sheet",
        "kind": "instant",
        "units": ("shares",),
        "tags": ("CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"),
    },
}

_DEBT_CURRENT_LONG_TERM_TAGS = (
    "LongTermDebtAndFinanceLeaseObligationsCurrent",
    "LongTermDebtCurrent",
)
_DEBT_NONCURRENT_TAGS = (
    "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
    "LongTermDebtNoncurrent",
)
_Q4_DERIVABLE_METRICS = {
    "revenue",
    "gross_profit",
    "operating_income",
    "operating_expense",
    "net_income",
    "operating_cash_flow",
    "capital_expenditure",
}


def _ticker_key(value: Any) -> str:
    return str(value or "").upper().strip().replace(".", "-")


def _parse_date(value: Any) -> dt.date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _duration_days(item: dict[str, Any]) -> int | None:
    start = _parse_date(item.get("start"))
    end = _parse_date(item.get("end"))
    if start is None or end is None:
        return None
    return (end - start).days


def _fact_rank(item: dict[str, Any]) -> tuple[str, int, str]:
    form = str(item.get("form") or "")
    accession = item.get("accession") or item.get("accn") or ""
    return (str(item.get("filed") or ""), int(form.endswith("/A")), str(accession))


def _coerce_number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not pd.notna(result):
        return None
    return result


def _choose_unit(units: Any, preferred_units: tuple[str, ...]) -> tuple[str, list[dict[str, Any]]] | None:
    if not isinstance(units, dict):
        return None
    normalized = {str(key).replace(" ", "").casefold(): str(key) for key in units}
    for preferred in preferred_units:
        key = normalized.get(str(preferred).replace(" ", "").casefold())
        values = units.get(key) if key is not None else None
        if isinstance(values, list):
            return key, values
    return None


def _fact_definitions(
    company_facts: dict[str, Any],
    tags: tuple[str, ...],
    preferred_units: tuple[str, ...],
) -> list[tuple[str, dict[str, Any], tuple[str, list[dict[str, Any]]]]]:
    facts = company_facts.get("facts") if isinstance(company_facts, dict) else None
    if not isinstance(facts, dict):
        return []
    definitions = []
    for tag in tags:
        for taxonomy in ("us-gaap", "dei"):
            taxonomy_facts = facts.get(taxonomy)
            if not isinstance(taxonomy_facts, dict) or not isinstance(taxonomy_facts.get(tag), dict):
                continue
            fact = taxonomy_facts[tag]
            unit_values = _choose_unit(fact.get("units"), preferred_units)
            if unit_values is not None:
                definitions.append((tag, fact, unit_values))
    return definitions


def _select_period_facts(
    company_facts: dict[str, Any],
    spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    definitions = _fact_definitions(
        company_facts,
        tuple(spec.get("tags", ())),
        tuple(spec.get("units", ())),
    )
    if not definitions:
        return [], []
    annual: dict[str, dict[str, Any]] = {}
    quarterly: dict[str, dict[str, Any]] = {}
    kind = str(spec.get("kind") or "flow")

    for tag, _fact, unit_values in definitions:
        unit, values = unit_values
        for raw in values:
            if not isinstance(raw, dict):
                continue
            value = _coerce_number(raw.get("val"))
            end = str(raw.get("end") or "")[:10]
            form = str(raw.get("form") or "")
            if value is None or not end:
                continue
            duration = _duration_days(raw)
            if kind == "flow":
                annual_ok = form in _ANNUAL_FORMS and str(raw.get("fp") or "").upper() == "FY" and duration is not None and 300 <= duration <= 380
                quarterly_ok = form in _QUARTERLY_FORMS and str(raw.get("fp") or "").upper() in {"Q1", "Q2", "Q3"} and duration is not None and 70 <= duration <= 110
            else:
                annual_ok = form in _ANNUAL_FORMS
                quarterly_ok = form in _QUARTERLY_FORMS
            if not annual_ok and not quarterly_ok:
                continue
            item = {
                "value": abs(value) if spec.get("absolute") else value,
                "start": str(raw.get("start") or "")[:10],
                "end": end,
                "filed": str(raw.get("filed") or "")[:10],
                "form": form,
                "fp": str(raw.get("fp") or ""),
                "fy": raw.get("fy"),
                "accession": str(raw.get("accn") or ""),
                "tag": tag,
                "unit": unit,
                "derived": False,
            }
            target = annual if annual_ok else quarterly
            current = target.get(end)
            if current is None or _fact_rank(item) > _fact_rank(current):
                target[end] = item

    return sorted(annual.values(), key=lambda item: item["end"]), sorted(quarterly.values(), key=lambda item: item["end"])


def _derive_q4(annual: list[dict[str, Any]], quarterly: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = list(quarterly)
    direct_by_fy: dict[Any, list[dict[str, Any]]] = {}
    for item in quarterly:
        direct_by_fy.setdefault(item.get("fy"), []).append(item)
    existing_ends = {str(item.get("end") or "") for item in output}
    for annual_item in annual:
        fiscal_year = annual_item.get("fy")
        direct = direct_by_fy.get(fiscal_year, [])
        if len(direct) != 3 or annual_item.get("end") in existing_ends:
            continue
        direct_fps = {str(item.get("fp") or "").upper() for item in direct}
        if direct_fps != {"Q1", "Q2", "Q3"}:
            continue
        value = float(annual_item["value"]) - sum(float(item["value"]) for item in direct)
        output.append({
            **annual_item,
            "value": value,
            "start": "",
            "form": "10-K derived Q4",
            "fp": "Q4",
            "derived": True,
        })
    return sorted(output, key=lambda item: item["end"])


def _series_by_end(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("end") or ""): item for item in items if str(item.get("end") or "")}


def _derive_free_cash_flow(
    operating: list[dict[str, Any]],
    capex: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    operating_map = _series_by_end(operating)
    capex_map = _series_by_end(capex)
    output = []
    for end in sorted(set(operating_map) & set(capex_map)):
        base = operating_map[end]
        capex_item = capex_map[end]
        output.append({
            **base,
            "value": float(base["value"]) - abs(float(capex_item["value"])),
            "tag": f'{base.get("tag", "")}-{capex_item.get("tag", "")}',
            "derived": True,
        })
    return output


def _component_debt_series(company_facts: dict[str, Any], period: str) -> list[dict[str, Any]]:
    def selected(tags: tuple[str, ...]) -> dict[str, dict[str, Any]]:
        spec = {"kind": "instant", "units": ("USD",), "tags": tags}
        annual, quarterly = _select_period_facts(company_facts, spec)
        return _series_by_end(annual if period == "annual" else quarterly)

    current_total = selected(("DebtCurrent",))
    current_long_term = selected(_DEBT_CURRENT_LONG_TERM_TAGS)
    short_term_borrowings = selected(("ShortTermBorrowings",))
    noncurrent = selected(_DEBT_NONCURRENT_TAGS)
    current = dict(current_total)
    for end in sorted((set(current_long_term) | set(short_term_borrowings)) - set(current)):
        long_term_item = current_long_term.get(end)
        short_term_item = short_term_borrowings.get(end)
        base = long_term_item or short_term_item
        if base is None:
            continue
        current[end] = {
            **base,
            "value": float(long_term_item.get("value", 0.0) if long_term_item else 0.0)
            + float(short_term_item.get("value", 0.0) if short_term_item else 0.0),
            "tag": "+".join(
                item.get("tag", "") for item in (long_term_item, short_term_item) if item is not None
            ),
            "derived": bool(long_term_item and short_term_item),
        }
    output = []
    for end in sorted(set(current) & set(noncurrent)):
        output.append({
            **current[end],
            "value": float(current[end]["value"]) + float(noncurrent[end]["value"]),
            "tag": f'{current[end].get("tag", "")}+{noncurrent[end].get("tag", "")}',
            "derived": True,
        })
    return output


def _build_frame(series: dict[str, list[dict[str, Any]]], metric_keys: list[str], limit: int) -> Any:
    dates = sorted({item["end"] for key in metric_keys for item in series.get(key, [])})[-limit:]
    if not dates:
        return pd.DataFrame()
    values: dict[str, list[float | None]] = {}
    for key in metric_keys:
        row = "Free Cash Flow" if key == "free_cash_flow" else _METRIC_SPECS[key]["row"]
        by_end = _series_by_end(series.get(key, []))
        values[row] = [by_end.get(end, {}).get("value") for end in dates]
    frame = pd.DataFrame(values, index=pd.to_datetime(dates)).transpose()
    return frame.dropna(axis=0, how="all")


def _normalize_company_facts(company_facts: dict[str, Any]) -> dict[str, Any]:
    annual_series: dict[str, list[dict[str, Any]]] = {}
    quarterly_series: dict[str, list[dict[str, Any]]] = {}
    provenance: dict[str, dict[str, dict[str, Any]]] = {}

    for key, spec in _METRIC_SPECS.items():
        annual, quarterly = _select_period_facts(company_facts, spec)
        if key == "total_debt":
            component_annual = _component_debt_series(company_facts, "annual")
            component_quarterly = _component_debt_series(company_facts, "quarterly")
            if component_annual:
                annual = component_annual
            if component_quarterly:
                quarterly = component_quarterly
        if key in _Q4_DERIVABLE_METRICS:
            quarterly = _derive_q4(annual, quarterly)
        annual_series[key] = annual[-10:]
        quarterly_series[key] = quarterly[-12:]

    annual_series["free_cash_flow"] = _derive_free_cash_flow(
        annual_series.get("operating_cash_flow", []), annual_series.get("capital_expenditure", [])
    )[-10:]
    quarterly_series["free_cash_flow"] = _derive_free_cash_flow(
        quarterly_series.get("operating_cash_flow", []), quarterly_series.get("capital_expenditure", [])
    )[-12:]

    for key in (*_METRIC_SPECS.keys(), "free_cash_flow"):
        row = "Free Cash Flow" if key == "free_cash_flow" else _METRIC_SPECS[key]["row"]
        provenance[row] = {
            "annual": {item["end"]: dict(item) for item in annual_series.get(key, [])},
            "quarterly": {item["end"]: dict(item) for item in quarterly_series.get(key, [])},
        }

    financial_keys = [key for key, spec in _METRIC_SPECS.items() if spec["family"] == "financials"]
    cashflow_keys = [key for key, spec in _METRIC_SPECS.items() if spec["family"] == "cashflow"]
    cashflow_keys.append("free_cash_flow")
    balance_keys = [key for key, spec in _METRIC_SPECS.items() if spec["family"] == "balance_sheet"]

    frames = {
        "financials": _build_frame(annual_series, financial_keys, 10),
        "quarterly_financials": _build_frame(quarterly_series, financial_keys, 12),
        "cashflow": _build_frame(annual_series, cashflow_keys, 10),
        "quarterly_cashflow": _build_frame(quarterly_series, cashflow_keys, 12),
        "balance_sheet": _build_frame(annual_series, balance_keys, 10),
        "quarterly_balance_sheet": _build_frame(quarterly_series, balance_keys, 12),
    }
    return {"frames": frames, "provenance": provenance}


def _normalize_filings(submissions: dict[str, Any], cik: str) -> list[dict[str, Any]]:
    recent = submissions.get("filings", {}).get("recent", {}) if isinstance(submissions, dict) else {}
    if not isinstance(recent, dict):
        return []
    forms = recent.get("form") if isinstance(recent.get("form"), list) else []
    filings = []
    for index, form_value in enumerate(forms):
        form = str(form_value or "")
        if not form.startswith(_FILING_FORM_PREFIXES):
            continue

        def field(name: str) -> str:
            values = recent.get(name)
            return str(values[index] or "") if isinstance(values, list) and index < len(values) else ""

        accession = field("accessionNumber")
        document = field("primaryDocument")
        accession_path = accession.replace("-", "")
        url = ""
        if accession_path and document:
            url = SEC_ARCHIVES_URL.format(cik=str(int(cik)), accession=accession_path, document=document)
        description = field("primaryDocDescription") or field("items") or document
        filings.append({
            "form": form,
            "filed_date": field("filingDate"),
            "report_period": field("reportDate"),
            "description": description,
            "items": field("items"),
            "accession_number": accession,
            "document": document,
            "document_url": url,
        })
        if len(filings) >= 50:
            break
    return filings


def _normalize_frame_columns(frame: Any) -> Any:
    if frame is None or not hasattr(frame, "copy"):
        return pd.DataFrame()
    result = frame.copy()
    normalized = []
    for column in result.columns:
        try:
            normalized.append(pd.Timestamp(column).normalize())
        except Exception:
            normalized.append(column)
    result.columns = normalized
    return result


def merge_statement_frames(yahoo_frame: Any, sec_frame: Any) -> Any:
    """Merge two statement frames with non-null SEC cells taking precedence."""
    yahoo = _normalize_frame_columns(yahoo_frame)
    sec = _normalize_frame_columns(sec_frame)
    if yahoo.empty:
        try:
            return sec.reindex(columns=sorted(sec.columns, reverse=True))
        except Exception:
            return sec
    if sec.empty:
        return yahoo
    rows = list(yahoo.index) + [row for row in sec.index if row not in yahoo.index]
    columns = list(yahoo.columns) + [column for column in sec.columns if column not in yahoo.columns]
    merged = yahoo.reindex(index=rows, columns=columns)
    for row in sec.index:
        for column in sec.columns:
            value = sec.at[row, column]
            if pd.notna(value):
                merged.at[row, column] = value
    try:
        merged = merged.reindex(columns=sorted(merged.columns, reverse=True))
    except Exception:
        pass
    return merged


def merge_sec_frames(payload: dict[str, Any], sec_bundle: dict[str, Any]) -> dict[str, Any]:
    """Return a payload whose six statement frames prefer normalized SEC cells."""
    merged = dict(payload)
    frames = sec_bundle.get("frames") if isinstance(sec_bundle, dict) else None
    if not isinstance(frames, dict):
        return merged
    for key in (
        "financials",
        "quarterly_financials",
        "cashflow",
        "quarterly_cashflow",
        "balance_sheet",
        "quarterly_balance_sheet",
    ):
        merged[key] = merge_statement_frames(payload.get(key), frames.get(key))
    return merged


class SecEdgarService:
    """Fetch, cache, and normalize public SEC EDGAR company data."""

    _rate_lock = threading.Lock()
    _last_request_at = 0.0

    def __init__(
        self,
        cache_manager: CacheManager | None = None,
        *,
        session: Any = None,
        user_agent: str | None = None,
        sleep_fn: Any = time.sleep,
        monotonic_fn: Any = time.monotonic,
    ) -> None:
        self.cache = cache_manager or CacheManager()
        self.session = session or requests.Session()
        self.user_agent = str(
            user_agent or os.getenv("BUDGET_TERMINAL_SEC_USER_AGENT") or _DEFAULT_USER_AGENT
        ).strip()
        self.sleep_fn = sleep_fn
        self.monotonic_fn = monotonic_fn

    def _pace_request(self) -> None:
        with self._rate_lock:
            now = self.monotonic_fn()
            delay = SEC_REQUEST_INTERVAL_SECONDS - (now - self.__class__._last_request_at)
            if delay > 0:
                self.sleep_fn(delay)
            self.__class__._last_request_at = self.monotonic_fn()

    def _request_json(self, url: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(SEC_MAX_ATTEMPTS):
            self._pace_request()
            retryable = True
            try:
                response = self.session.get(
                    url,
                    headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
                    timeout=SEC_REQUEST_TIMEOUT_SECONDS,
                )
                status_code = int(getattr(response, "status_code", 200) or 200)
                if status_code == 429 or 500 <= status_code < 600:
                    raise RuntimeError(f"SEC returned HTTP {status_code}")
                retryable = False
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("SEC response was not a JSON object")
                return payload
            except Exception as exc:
                last_error = exc
                if retryable and attempt < SEC_MAX_ATTEMPTS - 1:
                    self.sleep_fn(min(0.5 * (2 ** attempt), 2.0))
                    continue
                break
        raise RuntimeError(str(last_error or "SEC request failed"))

    def _cached_json(
        self,
        namespace: str,
        cache_key: str,
        url: str,
        *,
        ttl_seconds: int,
        force_refresh: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not force_refresh:
            cached = self.cache.get_json_payload(
                namespace,
                cache_key,
                max_age_seconds=ttl_seconds,
                return_metadata=True,
            )
            if cached is not None:
                payload, metadata = cached
                return payload, {"freshness": "cached", **metadata}
        try:
            payload = self._request_json(url)
            self.cache.save_json_payload(namespace, cache_key, payload)
            return payload, {"freshness": "fresh", "cache_age_seconds": 0.0}
        except Exception as exc:
            stale = self.cache.get_json_payload(
                namespace,
                cache_key,
                max_age_seconds=SEC_STALE_FALLBACK_SECONDS,
                allow_stale=True,
                return_metadata=True,
            )
            if stale is not None:
                payload, metadata = stale
                if float(metadata.get("cache_age_seconds", 0.0) or 0.0) <= SEC_STALE_FALLBACK_SECONDS:
                    return payload, {"freshness": "stale", "warning": str(exc), **metadata}
            raise

    def _ticker_entry(self, ticker: str, *, force_refresh: bool) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        payload, metadata = self._cached_json(
            "sec_tickers",
            "company_tickers",
            SEC_TICKERS_URL,
            ttl_seconds=SEC_TICKERS_TTL_SECONDS,
            force_refresh=force_refresh,
        )
        wanted = _ticker_key(ticker)
        for item in payload.values():
            if isinstance(item, dict) and _ticker_key(item.get("ticker")) == wanted:
                return item, metadata
        return None, metadata

    def fetch_company_bundle(self, ticker: Any, force_refresh: bool = False) -> dict[str, Any]:
        symbol = str(ticker or "").upper().strip()
        if not symbol:
            raise ValueError("Ticker is required for SEC lookup.")
        warnings: list[str] = []
        try:
            entry, ticker_meta = self._ticker_entry(symbol, force_refresh=force_refresh)
        except Exception as exc:
            return {
                "available": False,
                "ticker": symbol,
                "frames": {},
                "filings": [],
                "provenance": {},
                "freshness": "failed",
                "statement_freshness": "failed",
                "cache_age_seconds": 0.0,
                "warnings": [f"SEC ticker lookup failed: {exc}"],
            }
        if entry is None:
            return {
                "available": False,
                "ticker": symbol,
                "frames": {},
                "filings": [],
                "provenance": {},
                "freshness": ticker_meta.get("freshness", "unknown"),
                "statement_freshness": "unavailable",
                "cache_age_seconds": float(ticker_meta.get("cache_age_seconds", 0.0) or 0.0),
                "warnings": ["No domestic SEC filer mapping was found; using Yahoo data only."],
            }

        cik = str(int(entry.get("cik_str"))).zfill(10)
        facts: dict[str, Any] = {}
        submissions: dict[str, Any] = {}
        endpoint_meta: dict[str, dict[str, Any]] = {"tickers": ticker_meta}
        for endpoint, namespace, url, ttl in (
            ("facts", "sec_companyfacts", SEC_COMPANY_FACTS_URL.format(cik=cik), SEC_FACTS_TTL_SECONDS),
            ("submissions", "sec_submissions", SEC_SUBMISSIONS_URL.format(cik=cik), SEC_SUBMISSIONS_TTL_SECONDS),
        ):
            try:
                payload, metadata = self._cached_json(
                    namespace,
                    cik,
                    url,
                    ttl_seconds=ttl,
                    force_refresh=force_refresh,
                )
                endpoint_meta[endpoint] = metadata
                if metadata.get("warning"):
                    warnings.append(f"SEC {endpoint} refresh failed; using cached data: {metadata['warning']}")
                if endpoint == "facts":
                    facts = payload
                else:
                    submissions = payload
            except Exception as exc:
                endpoint_meta[endpoint] = {"freshness": "failed"}
                warnings.append(f"SEC {endpoint} unavailable: {exc}")

        normalized = _normalize_company_facts(facts) if facts else {"frames": {}, "provenance": {}}
        frames = normalized.get("frames", {})
        has_statements = any(not getattr(frame, "empty", True) for frame in frames.values())
        filings = _normalize_filings(submissions, cik) if submissions else []
        freshness_values = {str(meta.get("freshness") or "unknown") for meta in endpoint_meta.values()}
        if "stale" in freshness_values:
            freshness = "stale"
        elif "fresh" in freshness_values:
            freshness = "fresh"
        elif "cached" in freshness_values:
            freshness = "cached"
        else:
            freshness = "failed"
        if not has_statements:
            warnings.append("No supported domestic 10-K/10-Q XBRL facts were available; using Yahoo statements only.")
        cache_age_seconds = max(
            (float(meta.get("cache_age_seconds", 0.0) or 0.0) for meta in endpoint_meta.values()),
            default=0.0,
        )
        statement_freshness = str(endpoint_meta.get("facts", {}).get("freshness") or "failed")

        return {
            "available": bool(has_statements or filings),
            "statements_available": has_statements,
            "ticker": symbol,
            "cik": cik,
            "entity_name": str(submissions.get("name") or facts.get("entityName") or entry.get("title") or symbol),
            "sic": str(submissions.get("sic") or ""),
            "sic_description": str(submissions.get("sicDescription") or ""),
            "frames": frames,
            "filings": filings,
            "provenance": normalized.get("provenance", {}),
            "freshness": freshness,
            "statement_freshness": statement_freshness,
            "cache_age_seconds": cache_age_seconds,
            "endpoint_meta": endpoint_meta,
            "warnings": warnings,
            "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        }


def fetch_company_bundle(
    ticker: Any,
    force_refresh: bool = False,
    *,
    service: SecEdgarService | None = None,
) -> dict[str, Any]:
    """Fetch the normalized SEC company bundle using the shared service contract."""
    return (service or SecEdgarService()).fetch_company_bundle(ticker, force_refresh=force_refresh)
