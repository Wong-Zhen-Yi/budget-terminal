from __future__ import annotations

import datetime
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.cache import CacheManager
from budget_terminal_app.services.sec_edgar import (
    SEC_COMPANY_FACTS_URL,
    SEC_SUBMISSIONS_URL,
    SEC_TICKERS_URL,
    SecEdgarService,
    merge_statement_frames,
    _normalize_company_facts,
)
from budget_terminal_app.dependencies import pd


def _entry(
    value: float,
    *,
    start: str | None,
    end: str,
    filed: str,
    form: str,
    fp: str,
    fy: int,
    accession: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "val": value,
        "end": end,
        "filed": filed,
        "form": form,
        "fp": fp,
        "fy": fy,
        "accn": accession,
    }
    if start:
        payload["start"] = start
    return payload


def _fixture_companyfacts() -> dict[str, object]:
    annual_old = _entry(
        390.0,
        start="2024-01-01",
        end="2024-12-31",
        filed="2025-02-01",
        form="10-K",
        fp="FY",
        fy=2024,
        accession="0001-24-000001",
    )
    annual_amended = {
        **annual_old,
        "val": 400.0,
        "filed": "2025-03-01",
        "form": "10-K/A",
        "accn": "0001-24-000002",
    }
    quarters = [
        _entry(
            90.0,
            start="2024-01-01",
            end="2024-03-31",
            filed="2024-05-01",
            form="10-Q",
            fp="Q1",
            fy=2024,
            accession="0001-24-000010",
        ),
        _entry(
            95.0,
            start="2024-04-01",
            end="2024-06-30",
            filed="2024-08-01",
            form="10-Q",
            fp="Q2",
            fy=2024,
            accession="0001-24-000011",
        ),
        _entry(
            100.0,
            start="2024-07-01",
            end="2024-09-30",
            filed="2024-11-01",
            form="10-Q",
            fp="Q3",
            fy=2024,
            accession="0001-24-000012",
        ),
        # This cumulative Q2 value must not replace the direct-duration quarter.
        _entry(
            185.0,
            start="2024-01-01",
            end="2024-06-30",
            filed="2024-08-01",
            form="10-Q",
            fp="Q2",
            fy=2024,
            accession="0001-24-000013",
        ),
    ]
    cashflow_annual = {**annual_amended, "val": 80.0, "accn": "0001-24-000020"}
    capex_annual = {**annual_amended, "val": 20.0, "accn": "0001-24-000021"}
    cashflow_quarters = [{**item, "val": value} for item, value in zip(quarters[:3], (18.0, 19.0, 20.0))]
    capex_quarters = [{**item, "val": value} for item, value in zip(quarters[:3], (4.0, 5.0, 6.0))]
    instant = _entry(
        55.0,
        start=None,
        end="2024-09-30",
        filed="2024-11-01",
        form="10-Q",
        fp="Q3",
        fy=2024,
        accession="0001-24-000030",
    )
    annual_instant = _entry(
        60.0,
        start=None,
        end="2024-12-31",
        filed="2025-02-01",
        form="10-K",
        fp="FY",
        fy=2024,
        accession="0001-24-000031",
    )
    return {
        "entityName": "Fixture Holdings",
        "facts": {
            "us-gaap": {
                # Wrong unit verifies that the next declared revenue alias is tried.
                "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"shares": quarters}},
                "Revenues": {"units": {"USD": [annual_old, annual_amended, *quarters]}},
                "NetIncomeLoss": {"units": {"USD": [{**annual_amended, "val": 40.0}, *[{**item, "val": value} for item, value in zip(quarters[:3], (8.0, 9.0, 10.0))]]}},
                "SellingGeneralAndAdministrativeExpense": {
                    "units": {
                        "USD": [
                            {**annual_amended, "val": 40.0},
                            *[{**item, "val": value} for item, value in zip(quarters[:3], (8.0, 9.0, 10.0))],
                        ]
                    }
                },
                "ResearchAndDevelopmentExpense": {
                    "units": {
                        "USD": [
                            {**annual_amended, "val": 20.0},
                            *[{**item, "val": value} for item, value in zip(quarters[:3], (4.0, 5.0, 6.0))],
                        ]
                    }
                },
                "WeightedAverageNumberOfDilutedSharesOutstanding": {
                    "units": {
                        "shares": [
                            {**annual_amended, "val": 100.0},
                            *[{**item, "val": 100.0} for item in quarters[:3]],
                        ]
                    }
                },
                "EarningsPerShareDiluted": {
                    "units": {
                        "USD/shares": [
                            {**annual_amended, "val": 4.0},
                            *[{**item, "val": 1.0} for item in quarters[:3]],
                        ]
                    }
                },
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [cashflow_annual, *cashflow_quarters]}},
                "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [capex_annual, *capex_quarters]}},
                "CashCashEquivalentsAndShortTermInvestments": {"units": {"USD": [instant, annual_instant]}},
                "MarketableSecuritiesCurrent": {"units": {"USD": [{**instant, "val": 12.0}]}},
                "LongTermDebt": {"units": {"USD": [{**instant, "val": 30.0}]}},
                "CommonStockSharesOutstanding": {
                    "units": {"shares": [{**instant, "val": 10.0}, {**annual_instant, "val": 11.0}]}
                },
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {
                                **instant,
                                "end": "2024-10-15",
                                "filed": "2024-11-02",
                                "val": 10.5,
                            }
                        ]
                    }
                }
            },
        },
    }


def _fixture_submissions() -> dict[str, object]:
    return {
        "name": "Fixture Holdings",
        "sic": "3571",
        "sicDescription": "Electronic Computers",
        "filings": {
            "recent": {
                "form": ["10-K/A", "10-Q", "8-K", "4"],
                "filingDate": ["2025-03-01", "2024-11-01", "2024-10-15", "2024-10-01"],
                "reportDate": ["2024-12-31", "2024-09-30", "2024-10-15", "2024-10-01"],
                "accessionNumber": ["0001-24-000002", "0001-24-000012", "0001-24-000040", "0001-24-000041"],
                "primaryDocument": ["annual.htm", "quarter.htm", "current.htm", "ownership.htm"],
                "primaryDocDescription": ["Annual amendment", "Quarterly report", "Current report", "Ownership"],
                "items": ["", "", "2.02,9.01", ""],
            }
        },
    }


class _Response:
    def __init__(self, payload: dict[str, object] | None = None, status_code: int = 200) -> None:
        self._payload = payload or {}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, object]:
        return self._payload


class _Session:
    def __init__(self, payloads: dict[str, dict[str, object]], statuses: list[int] | None = None) -> None:
        self.payloads = payloads
        self.statuses = list(statuses or [])
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> _Response:
        self.calls.append((url, dict(kwargs)))
        status = self.statuses.pop(0) if self.statuses else 200
        return _Response(self.payloads.get(url, {}), status)


def test_normalization_and_bundle_contract() -> None:
    normalized = _normalize_company_facts(_fixture_companyfacts())
    frames = normalized["frames"]
    annual = frames["financials"]
    quarterly = frames["quarterly_financials"]
    assert annual.loc["Total Revenue"].iloc[-1] == 400.0
    assert normalized["provenance"]["Total Revenue"]["annual"]["2024-12-31"]["accession"] == "0001-24-000002"
    assert quarterly.loc["Total Revenue", "2024-06-30"] == 95.0
    assert quarterly.loc["Total Revenue", "2024-12-31"] == 115.0
    assert normalized["provenance"]["Total Revenue"]["quarterly"]["2024-12-31"]["derived"] is True
    assert quarterly.loc["Selling General And Administrative Expense", "2024-12-31"] == 13.0
    assert quarterly.loc["Research And Development Expense", "2024-12-31"] == 5.0
    assert pd.isna(quarterly.loc["Diluted Average Shares", "2024-12-31"])
    assert pd.isna(quarterly.loc["Diluted EPS", "2024-12-31"])
    assert "2024-12-31" not in normalized["provenance"]["Diluted Average Shares"]["quarterly"]
    assert frames["cashflow"].loc["Free Cash Flow"].iloc[-1] == 60.0
    balance_quarterly = frames["quarterly_balance_sheet"]
    assert balance_quarterly.loc["Marketable Securities Current", "2024-09-30"] == 12.0
    assert balance_quarterly.loc["Common Stock Shares Outstanding", "2024-12-31"] == 11.0
    assert pd.Timestamp("2024-10-15") not in balance_quarterly.columns
    assert "Gross Profit" not in annual.index
    yahoo = pd.DataFrame(
        {pd.Timestamp("2024-12-31"): [390.0, 7.0], pd.Timestamp("2023-12-31"): [300.0, 6.0]},
        index=["Total Revenue", "Yahoo Custom Row"],
    )
    sec = pd.DataFrame(
        {pd.Timestamp("2024-12-31"): [400.0]},
        index=["Total Revenue"],
    )
    merged = merge_statement_frames(yahoo, sec)
    assert merged.loc["Total Revenue", pd.Timestamp("2024-12-31")] == 400.0
    assert merged.loc["Total Revenue", pd.Timestamp("2023-12-31")] == 300.0
    assert merged.loc["Yahoo Custom Row", pd.Timestamp("2024-12-31")] == 7.0

    apple_style_yahoo = pd.DataFrame(
        {
            pd.Timestamp("2025-09-30"): [416.0, 90.0, 12.0],
            pd.Timestamp("2024-09-30"): [391.0, 97.0, 11.0],
        },
        index=["Total Revenue", "Total Debt", "Yahoo Custom Row"],
    )
    apple_style_sec = pd.DataFrame(
        {
            pd.Timestamp("2025-09-27"): [416.0, 99.0],
            pd.Timestamp("2024-09-28"): [391.0, 107.0],
        },
        index=["Total Revenue", "Total Debt"],
    )
    apple_style_merged = merge_statement_frames(apple_style_yahoo, apple_style_sec)
    assert list(apple_style_merged.columns) == [
        pd.Timestamp("2025-09-27"),
        pd.Timestamp("2024-09-28"),
    ]
    assert apple_style_merged.loc["Total Debt", pd.Timestamp("2025-09-27")] == 99.0
    assert apple_style_merged.loc["Yahoo Custom Row", pd.Timestamp("2025-09-27")] == 12.0

    instant = {
        "end": "2024-09-30",
        "filed": "2024-11-01",
        "form": "10-Q",
        "fp": "Q3",
        "fy": 2024,
        "accn": "debt-test",
    }
    split_debt = _normalize_company_facts({
        "facts": {
            "us-gaap": {
                "DebtCurrent": {"units": {"USD": [{**instant, "val": 10.0}]}},
                "LongTermDebt": {"units": {"USD": [{**instant, "val": 90.0}]}},
                "LongTermDebtNoncurrent": {"units": {"USD": [{**instant, "val": 90.0}]}},
            }
        }
    })["frames"]["quarterly_balance_sheet"]
    assert split_debt.loc["Total Debt", "2024-09-30"] == 100.0

    with tempfile.TemporaryDirectory(prefix="budget-terminal-sec-", ignore_cleanup_errors=True) as temp_dir:
        cik = "0000000001"
        payloads = {
            SEC_TICKERS_URL: {"0": {"ticker": "BRK-B", "cik_str": 1, "title": "Fixture Holdings"}},
            SEC_COMPANY_FACTS_URL.format(cik=cik): _fixture_companyfacts(),
            SEC_SUBMISSIONS_URL.format(cik=cik): _fixture_submissions(),
        }
        session = _Session(payloads)
        SecEdgarService._last_request_at = 0.0
        service = SecEdgarService(
            CacheManager(Path(temp_dir) / "cache.db"),
            session=session,
            user_agent="BudgetTerminal test maintainers-at-budget-terminal.invalid",
            sleep_fn=lambda _seconds: None,
        )
        bundle = service.fetch_company_bundle("brk.b")
        assert bundle["available"] is True
        assert bundle["statements_available"] is True
        assert bundle["cik"] == cik
        assert len(bundle["filings"]) == 3
        filing = bundle["filings"][0]
        assert filing["filed_date"] == "2025-03-01"
        assert filing["accession_number"] == "0001-24-000002"
        assert filing["document_url"] == "https://www.sec.gov/Archives/edgar/data/1/000124000002/annual.htm"
        assert all(call[1]["timeout"] == 15 for call in session.calls)
        assert all("BudgetTerminal test" in call[1]["headers"]["User-Agent"] for call in session.calls)
        old_submissions = (datetime.datetime.now() - datetime.timedelta(minutes=16)).isoformat()
        with sqlite3.connect(Path(temp_dir) / "cache.db") as connection:
            connection.execute(
                "UPDATE json_payload_cache SET last_updated=? WHERE namespace=? AND cache_key=?",
                (old_submissions, "sec_submissions", cik),
            )
        mixed_freshness = service.fetch_company_bundle("BRK-B")
        assert mixed_freshness["freshness"] == "fresh"
        assert mixed_freshness["statement_freshness"] == "cached"


def test_cache_stale_fallback_and_retry() -> None:
    with tempfile.TemporaryDirectory(prefix="budget-terminal-sec-cache-", ignore_cleanup_errors=True) as temp_dir:
        cache_path = Path(temp_dir) / "cache.db"
        cache = CacheManager(cache_path)
        cache.save_json_payload("fixture", "stale", {"ok": True})
        old = (datetime.datetime.now() - datetime.timedelta(hours=2)).isoformat()
        with sqlite3.connect(cache_path) as connection:
            connection.execute(
                "UPDATE json_payload_cache SET last_updated=? WHERE namespace=? AND cache_key=?",
                (old, "fixture", "stale"),
            )
        failing = _Session({}, statuses=[500, 429, 500])
        sleeps: list[float] = []
        SecEdgarService._last_request_at = 0.0
        service = SecEdgarService(cache, session=failing, sleep_fn=sleeps.append)
        payload, metadata = service._cached_json(
            "fixture",
            "stale",
            "https://data.sec.gov/test.json",
            ttl_seconds=60,
            force_refresh=False,
        )
        assert payload == {"ok": True}
        assert metadata["freshness"] == "stale"
        assert len(failing.calls) == 3
        assert any(delay >= 0.5 for delay in sleeps)
        forbidden = _Session({}, statuses=[403, 200, 200])
        forbidden_service = SecEdgarService(cache, session=forbidden, sleep_fn=lambda _seconds: None)
        try:
            forbidden_service._request_json("https://www.sec.gov/forbidden.json")
        except RuntimeError:
            pass
        else:
            raise AssertionError("HTTP 403 should fail without retrying")
        assert len(forbidden.calls) == 1
        assert cache.clear_all() is True
        assert cache.get_json_payload("fixture", "stale", max_age_seconds=999999) is None


def main() -> None:
    test_normalization_and_bundle_contract()
    test_cache_stale_fallback_and_retry()
    print("SEC EDGAR service tests passed")


if __name__ == "__main__":
    main()
