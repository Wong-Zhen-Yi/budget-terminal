from __future__ import annotations

import csv
import io
import re
import threading
import zipfile
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree as ET

import requests
import yfinance as yf
from bs4 import BeautifulSoup


DEFAULT_TIMEOUT = 20
YF_ETF_LOCK = threading.Lock()


class EtfHoldingsError(RuntimeError):
    """Raised when an ETF holdings request fails."""


class UnsupportedEtfIssuerError(EtfHoldingsError):
    """Raised when no supported official issuer source is available."""


@dataclass
class EtfHolding:
    symbol: str
    name: str
    weight: float | None
    sector: str = ""


@dataclass
class EtfHoldingsResult:
    ticker: str
    fund_name: str = ""
    issuer: str = ""
    as_of_date: str = ""
    expense_ratio: str = "--"
    net_assets: str = "--"
    holdings: list[EtfHolding] = field(default_factory=list)
    sector_breakdown: dict[str, float] = field(default_factory=dict)
    source_url: str = ""
    is_partial: bool = False
    coverage_note: str = ""


class _BaseIssuerProvider:
    issuer = ""

    def __init__(self, session: requests.Session):
        self.session = session

    def fetch(self, ticker: str) -> EtfHoldingsResult | None:
        raise NotImplementedError

    def _get(self, url: str, **kwargs: Any) -> requests.Response:
        response = self.session.get(url, timeout=DEFAULT_TIMEOUT, **kwargs)
        response.raise_for_status()
        return response

    def _clean_text(self, value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def _normalize_weight(self, value: Any, *, scale: str = "auto") -> float | None:
        text = self._clean_text(value).replace("%", "").replace(",", "")
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        if scale == "percent":
            return number / 100.0
        if scale == "fraction":
            return number
        return number / 100.0 if abs(number) > 1 else number

    def _format_percent_string(self, value: Any) -> str:
        text = self._clean_text(value).replace(" ", "").rstrip("%")
        if not text:
            return "--"
        try:
            return f"{float(text):.2f}%"
        except ValueError:
            return f"{text}%"

    def _format_large_number(self, value: Any) -> str:
        text = self._clean_text(value).replace("$", "").replace(",", "")
        if not text:
            return "--"
        try:
            number = float(text)
        except ValueError:
            return self._clean_text(value)
        abs_value = abs(number)
        if abs_value >= 1_000_000_000_000:
            return f"{number / 1_000_000_000_000:.2f}T"
        if abs_value >= 1_000_000_000:
            return f"{number / 1_000_000_000:.2f}B"
        if abs_value >= 1_000_000:
            return f"{number / 1_000_000:.2f}M"
        if abs_value >= 1_000:
            return f"{number / 1_000:.2f}K"
        return f"{number:.2f}"


class InvescoIssuerProvider(_BaseIssuerProvider):
    issuer = "Invesco"
    holdings_url = "https://www.invesco.com/us/financial-products/etfs/holdings"
    qqq_about_url = "https://www.invesco.com/qqq-etf/en/about.html"
    qqq_holdings_api_url = "https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/QQQ/holdings/fund"
    qqq_holdings_resource_path = (
        "/content/invesco/qqq-etf/en/about/jcr:content/root/container/container_742249799/"
        "sectioncomponent_1252524195/container/view_all_holdings"
    )
    _DYNAMIC_NON_EQUITY_CODES = {"CURR", "CURRCOL", "IFUT", "SYN"}
    _DYNAMIC_NON_EQUITY_TEXT = ("cash", "currency", "future", "synthetic", "collateral")

    def fetch(self, ticker: str) -> EtfHoldingsResult | None:
        if str(ticker or "").upper().strip() == "QQQ":
            result = self._fetch_qqq_dynamic_holdings(ticker)
            if result is not None:
                return result
        response = self._get(
            self.holdings_url,
            params={"audienceType": "Investor", "ticker": ticker},
        )
        if "Fund Holdings" not in response.text and "holdings" not in response.text.lower():
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        title = self._extract_title(soup, ticker)
        as_of_date = self._extract_as_of(response.text)
        holdings = self._extract_holdings_table(soup)
        if not holdings:
            return None
        return EtfHoldingsResult(
            ticker=ticker,
            fund_name=title,
            issuer=self.issuer,
            as_of_date=as_of_date,
            holdings=holdings,
            source_url=response.url,
        )

    def _extract_title(self, soup: BeautifulSoup, ticker: str) -> str:
        heading = soup.find(["h1", "title"])
        text = self._clean_text(heading.get_text(" ", strip=True) if heading else ticker)
        if " - " in text:
            _, rhs = text.split(" - ", 1)
            return rhs.strip()
        return text

    def _extract_as_of(self, text: str) -> str:
        match = re.search(r"\bas of\b\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})", text, flags=re.IGNORECASE)
        return match.group(1) if match else ""

    def _extract_holdings_table(self, soup: BeautifulSoup) -> list[EtfHolding]:
        for table in soup.find_all("table"):
            headers = [self._clean_text(th.get_text(" ", strip=True)) for th in table.find_all("th")]
            lower_headers = [header.lower() for header in headers]
            if not lower_headers:
                continue
            if "ticker" not in lower_headers or "% of fund" not in lower_headers:
                continue
            symbol_idx = lower_headers.index("ticker")
            weight_idx = lower_headers.index("% of fund")
            name_idx = lower_headers.index("company") if "company" in lower_headers else None
            sector_idx = lower_headers.index("sector total") if "sector total" in lower_headers else None
            rows: list[EtfHolding] = []
            current_sector = ""
            for tr in table.find_all("tr"):
                cells = [self._clean_text(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
                if len(cells) <= max(symbol_idx, weight_idx, name_idx or 0, sector_idx or 0):
                    continue
                if sector_idx is not None and sector_idx < len(cells):
                    sector_value = cells[sector_idx]
                    if sector_value:
                        current_sector = sector_value
                symbol = cells[symbol_idx].upper()
                weight = self._normalize_weight(cells[weight_idx], scale="percent")
                if not symbol or weight is None:
                    continue
                rows.append(
                    EtfHolding(
                        symbol=symbol,
                        name=cells[name_idx] if name_idx is not None else "",
                        weight=weight,
                        sector=current_sector,
                    )
                )
            if rows:
                return rows
        return []

    def _fetch_qqq_dynamic_holdings(self, ticker: str) -> EtfHoldingsResult | None:
        response = self.session.get(
            self.qqq_holdings_api_url,
            params={"idType": "ticker", "interval": "monthly", "productType": "ETF"},
            headers={
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://www.invesco.com",
                "Referer": self.qqq_about_url,
                "ResourcePath": self.qqq_holdings_resource_path,
                "AppId": "invesco",
                "ComponentType": "view-all-holdings",
            },
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            return None
        holdings = self._extract_dynamic_holdings(payload)
        if not holdings:
            return None
        symbol = str(ticker or "").upper().strip()
        return EtfHoldingsResult(
            ticker=symbol,
            fund_name=f"Invesco {symbol}",
            issuer=self.issuer,
            as_of_date=self._clean_text(payload.get("effectiveDate")),
            holdings=holdings,
            source_url=response.url,
        )

    def _extract_dynamic_holdings(self, payload: Any) -> list[EtfHolding]:
        rows = payload.get("holdings") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        holdings: list[EtfHolding] = []
        for row in rows:
            if not isinstance(row, dict) or not self._is_dynamic_equity_row(row):
                continue
            symbol = self._clean_text(row.get("ticker")).upper()
            weight = self._normalize_weight(row.get("percentageOfTotalNetAssets"), scale="percent")
            if not symbol or weight is None:
                continue
            holdings.append(
                EtfHolding(
                    symbol=symbol,
                    name=self._clean_text(row.get("issuerName")),
                    weight=weight,
                    sector=self._clean_text(row.get("sectorName")),
                )
            )
        return holdings

    def _is_dynamic_equity_row(self, row: dict[str, Any]) -> bool:
        symbol = self._clean_text(row.get("ticker")).upper()
        if not symbol:
            return False
        security_code = self._clean_text(row.get("securityTypeCode")).upper()
        security_type = self._clean_text(row.get("securityTypeName")).casefold()
        if security_code in self._DYNAMIC_NON_EQUITY_CODES:
            return False
        return not any(token in security_type for token in self._DYNAMIC_NON_EQUITY_TEXT)


class SpdrIssuerProvider(_BaseIssuerProvider):
    issuer = "SPDR / State Street"
    template_url = "https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-{ticker}.xlsx"

    def fetch(self, ticker: str) -> EtfHoldingsResult | None:
        url = self.template_url.format(ticker=ticker.lower())
        response = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        rows = _parse_xlsx_rows(response.content)
        if not rows:
            return None
        holdings = self._extract_holdings(rows)
        if not holdings:
            return None
        return EtfHoldingsResult(
            ticker=ticker,
            fund_name=self._lookup_value(rows, ("fund name", "name")) or ticker,
            issuer=self.issuer,
            as_of_date=self._lookup_date(rows),
            expense_ratio=self._format_percent_string(self._lookup_value(rows, ("gross expense ratio", "net expense ratio", "expense ratio"))),
            net_assets=self._format_large_number(self._lookup_value(rows, ("net assets", "total net assets"))),
            holdings=holdings,
            source_url=url,
        )

    def _lookup_value(self, rows: list[list[str]], labels: tuple[str, ...]) -> str:
        label_set = {label.lower() for label in labels}
        for row in rows:
            cleaned = [self._clean_text(cell) for cell in row if self._clean_text(cell)]
            if len(cleaned) < 2:
                continue
            for idx, cell in enumerate(cleaned[:-1]):
                if cell.lower().rstrip(':') in label_set:
                    return cleaned[idx + 1]
        return ""

    def _lookup_date(self, rows: list[list[str]]) -> str:
        for row in rows:
            text = " ".join(self._clean_text(cell) for cell in row if self._clean_text(cell))
            match = re.search(r"\b(?:as of|date)\b[: ]+([A-Za-z]+\s+\d{1,2},\s+\d{4})", text, flags=re.IGNORECASE)
            if match:
                return match.group(1)
            match = re.search(r"\b(?:as of|date)\b[: ]+(\d{1,2}-[A-Za-z]{3}-\d{4})", text, flags=re.IGNORECASE)
            if match:
                return match.group(1)
        return ""

    def _extract_holdings(self, rows: list[list[str]]) -> list[EtfHolding]:
        header_index = -1
        symbol_idx = name_idx = weight_idx = sector_idx = None
        for index, row in enumerate(rows):
            lowered = [self._clean_text(cell).lower() for cell in row]
            if "ticker" in lowered and any("weight" in cell for cell in lowered):
                header_index = index
                symbol_idx = lowered.index("ticker")
                name_idx = lowered.index("name") if "name" in lowered else None
                sector_idx = next((i for i, cell in enumerate(lowered) if "sector" in cell), None)
                weight_idx = next((i for i, cell in enumerate(lowered) if "weight" in cell), None)
                break
        if header_index < 0 or weight_idx is None or symbol_idx is None:
            return []
        holdings: list[EtfHolding] = []
        for row in rows[header_index + 1 :]:
            if len(row) <= max(symbol_idx, weight_idx, name_idx or 0, sector_idx or 0):
                continue
            symbol = self._clean_text(row[symbol_idx]).upper()
            weight = self._normalize_weight(row[weight_idx], scale="percent")
            if not symbol or weight is None:
                continue
            holdings.append(
                EtfHolding(
                    symbol=symbol,
                    name=self._clean_text(row[name_idx]) if name_idx is not None else "",
                    weight=weight,
                    sector=self._clean_text(row[sector_idx]) if sector_idx is not None else "",
                )
            )
        return holdings


class IsharesIssuerProvider(_BaseIssuerProvider):
    issuer = "iShares / BlackRock"
    listing_url = "https://www.ishares.com/us/products/etf-investments"
    base_url = "https://www.ishares.com"

    def fetch(self, ticker: str) -> EtfHoldingsResult | None:
        listing_response = self._get(self.listing_url)
        product_path = self._find_product_path(listing_response.text, ticker)
        if not product_path:
            return None
        page_url = f"{self.base_url}{product_path}"
        page_response = self._get(page_url)
        csv_response = self._get(
            page_url,
            params={"fileType": "csv", "fileName": f"{ticker}_holdings", "dataType": "fund"},
        )
        holdings = self._parse_holdings_csv(csv_response.text)
        if not holdings:
            return None
        fund_name, as_of_date, expense_ratio, net_assets = self._parse_fund_page(page_response.text, ticker)
        return EtfHoldingsResult(
            ticker=ticker,
            fund_name=fund_name or ticker,
            issuer=self.issuer,
            as_of_date=as_of_date,
            expense_ratio=expense_ratio,
            net_assets=net_assets,
            holdings=holdings,
            source_url=page_url,
        )

    def _find_product_path(self, html: str, ticker: str) -> str:
        patterns = [
            rf'"localExchangeTicker"\s*:\s*"{re.escape(ticker)}".{{0,600}}?"productUrl"\s*:\s*"(?P<url>/us/products/[^"]+)"',
            rf'"productUrl"\s*:\s*"(?P<url>/us/products/[^"]+)".{{0,600}}?"localExchangeTicker"\s*:\s*"{re.escape(ticker)}"',
            rf'href="(?P<url>/us/products/[^"]+)".{{0,200}}?>\s*{re.escape(ticker)}\s*<',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
            if match:
                return match.group("url").replace("\\/", "/")
        return ""

    def _parse_holdings_csv(self, text: str) -> list[EtfHolding]:
        rows = list(csv.reader(io.StringIO(text)))
        header_index = -1
        headers: list[str] = []
        for index, row in enumerate(rows):
            lowered = [self._clean_text(cell).lower() for cell in row]
            if "ticker" in lowered and any("weight" in cell for cell in lowered):
                header_index = index
                headers = lowered
                break
        if header_index < 0:
            return []
        symbol_idx = headers.index("ticker")
        name_idx = headers.index("name") if "name" in headers else None
        sector_idx = headers.index("sector") if "sector" in headers else None
        weight_idx = next((i for i, header in enumerate(headers) if "weight" in header), None)
        if weight_idx is None:
            return []
        holdings: list[EtfHolding] = []
        for row in rows[header_index + 1 :]:
            if len(row) <= max(symbol_idx, weight_idx, name_idx or 0, sector_idx or 0):
                continue
            symbol = self._clean_text(row[symbol_idx]).upper()
            weight = self._normalize_weight(row[weight_idx], scale="percent")
            if not symbol or weight is None:
                continue
            holdings.append(
                EtfHolding(
                    symbol=symbol,
                    name=self._clean_text(row[name_idx]) if name_idx is not None else "",
                    weight=weight,
                    sector=self._clean_text(row[sector_idx]) if sector_idx is not None else "",
                )
            )
        return holdings

    def _parse_fund_page(self, html: str, ticker: str) -> tuple[str, str, str, str]:
        soup = BeautifulSoup(html, "html.parser")
        title = self._clean_text((soup.find("title") or soup.find("h1")).get_text(" ", strip=True) if (soup.find("title") or soup.find("h1")) else ticker)
        title = title.split("|", 1)[0].strip()
        as_of_date = ""
        expense_ratio = "--"
        net_assets = "--"
        text = soup.get_text(" ", strip=True)
        net_assets_match = re.search(r"Net Assets of Fund\s+as of\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})\s+\$?([\d,\.]+)", text, flags=re.IGNORECASE)
        if net_assets_match:
            as_of_date = net_assets_match.group(1)
            net_assets = self._format_large_number(net_assets_match.group(2))
        expense_match = re.search(r"Expense Ratio\s+([0-9\.]+%)", text, flags=re.IGNORECASE)
        if expense_match:
            expense_ratio = expense_match.group(1)
        return title, as_of_date, expense_ratio, net_assets


class VanguardIssuerProvider(_BaseIssuerProvider):
    issuer = "Vanguard"
    api_base = "https://investor.vanguard.com/investment-products/etfs/profile/api"

    def fetch(self, ticker: str) -> EtfHoldingsResult | None:
        profile = self._fetch_profile(ticker)
        if profile is None:
            return None
        holdings = self._fetch_all_holdings(ticker)
        if not holdings:
            return None
        fund_name = self._clean_text(profile.get("longName") or profile.get("shortName") or ticker)
        expense_ratio = self._extract_expense(profile)
        return EtfHoldingsResult(
            ticker=ticker,
            fund_name=fund_name,
            issuer=self.issuer,
            expense_ratio=expense_ratio,
            holdings=holdings,
            source_url=f"https://investor.vanguard.com/investment-products/etfs/profile/{ticker}",
        )

    def _fetch_profile(self, ticker: str) -> dict[str, Any] | None:
        try:
            resp = self.session.get(f"{self.api_base}/{ticker}/profile", timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError):
            return None

    def _fetch_all_holdings(self, ticker: str) -> list[EtfHolding]:
        holdings: list[EtfHolding] = []
        start = 0
        count = 500
        while True:
            try:
                resp = self._get(
                    f"{self.api_base}/{ticker}/portfolio-holding/stock",
                    params={"start": start, "count": count},
                )
                data = resp.json()
            except Exception:
                break
            items = data.get("holding", data.get("fund", {}).get("entity", []))
            if not items:
                break
            for item in items:
                symbol = self._clean_text(item.get("ticker")).upper()
                name = self._clean_text(item.get("longName") or item.get("shortName"))
                weight = self._normalize_weight(item.get("percentWeight"), scale="percent")
                if not symbol or weight is None:
                    continue
                holdings.append(EtfHolding(symbol=symbol, name=name, weight=weight))
            next_link = data.get("next", {})
            if isinstance(next_link, dict) and next_link.get("href"):
                start += count
            else:
                break
        return holdings

    def _extract_expense(self, profile: dict[str, Any]) -> str:
        ratio = profile.get("expenseRatio")
        if ratio is not None:
            try:
                return f"{float(ratio):.2f}%"
            except (ValueError, TypeError):
                pass
        return "--"


class FirstTrustIssuerProvider(_BaseIssuerProvider):
    issuer = "First Trust"
    holdings_url = "https://www.ftportfolios.com/Retail/Etf/EtfHoldings.aspx"

    def fetch(self, ticker: str) -> EtfHoldingsResult | None:
        try:
            resp = self._get(self.holdings_url, params={"Ticker": ticker})
        except requests.RequestException:
            return None
        if "EtfHoldings" not in resp.url and "Holdings" not in resp.text[:2000]:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        holdings = self._extract_holdings(soup)
        if not holdings:
            return None
        fund_name = self._extract_title(soup, ticker)
        return EtfHoldingsResult(
            ticker=ticker,
            fund_name=fund_name,
            issuer=self.issuer,
            holdings=holdings,
            source_url=resp.url,
        )

    def _extract_title(self, soup: BeautifulSoup, ticker: str) -> str:
        heading = soup.find("h1") or soup.find("title")
        if heading:
            text = self._clean_text(heading.get_text(" ", strip=True))
            for sep in (" - ", " | ", "("):
                if sep in text:
                    return text.split(sep, 1)[0].strip()
            return text
        return ticker

    def _extract_holdings(self, soup: BeautifulSoup) -> list[EtfHolding]:
        table = soup.find("table", class_="fundSilverGrid")
        if not table:
            for t in soup.find_all("table"):
                headers = [self._clean_text(th.get_text()).lower() for th in t.find_all("th")]
                if any("ticker" in h or "symbol" in h for h in headers) and any("weight" in h for h in headers):
                    table = t
                    break
        if not table:
            return []
        headers = [self._clean_text(th.get_text()).lower() for th in table.find_all("th")]
        symbol_idx = next((i for i, h in enumerate(headers) if "ticker" in h or "symbol" in h), None)
        name_idx = next((i for i, h in enumerate(headers) if "name" in h or "security" in h), None)
        weight_idx = next((i for i, h in enumerate(headers) if "weight" in h), None)
        if symbol_idx is None or weight_idx is None:
            return []
        holdings: list[EtfHolding] = []
        for tr in table.find_all("tr"):
            cells = [self._clean_text(td.get_text()) for td in tr.find_all("td")]
            if len(cells) <= max(symbol_idx, weight_idx, name_idx or 0):
                continue
            symbol = cells[symbol_idx].upper()
            weight = self._normalize_weight(cells[weight_idx], scale="percent")
            if not symbol or weight is None:
                continue
            holdings.append(
                EtfHolding(
                    symbol=symbol,
                    name=cells[name_idx] if name_idx is not None else "",
                    weight=weight,
                )
            )
        return holdings


class ProSharesIssuerProvider(_BaseIssuerProvider):
    issuer = "ProShares"
    base_url = "https://www.proshares.com/funds"

    def fetch(self, ticker: str) -> EtfHoldingsResult | None:
        url = f"{self.base_url}/{ticker.lower()}.html"
        try:
            resp = self.session.get(url, timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except requests.RequestException:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        holdings = self._extract_holdings(soup)
        if not holdings:
            return None
        fund_name = self._extract_title(soup, ticker)
        return EtfHoldingsResult(
            ticker=ticker,
            fund_name=fund_name,
            issuer=self.issuer,
            holdings=holdings,
            source_url=url,
        )

    def _extract_title(self, soup: BeautifulSoup, ticker: str) -> str:
        heading = soup.find("h1") or soup.find("title")
        if heading:
            text = self._clean_text(heading.get_text(" ", strip=True))
            for sep in (" - ", " | "):
                if sep in text:
                    return text.split(sep, 1)[0].strip()
            return text
        return ticker

    def _extract_holdings(self, soup: BeautifulSoup) -> list[EtfHolding]:
        table = soup.find("table", class_="holdings-table")
        if not table:
            for t in soup.find_all("table"):
                headers = [self._clean_text(th.get_text()).lower() for th in t.find_all("th")]
                if any("ticker" in h or "symbol" in h for h in headers) and any("weight" in h or "exposure" in h for h in headers):
                    table = t
                    break
        if not table:
            return []
        headers = [self._clean_text(th.get_text()).lower() for th in table.find_all("th")]
        symbol_idx = next((i for i, h in enumerate(headers) if "ticker" in h or "symbol" in h), None)
        name_idx = next((i for i, h in enumerate(headers) if "description" in h or "name" in h), None)
        weight_idx = next((i for i, h in enumerate(headers) if "exposure weight" in h or "weight" in h), None)
        if symbol_idx is None or weight_idx is None:
            return []
        holdings: list[EtfHolding] = []
        for tr in table.find_all("tr"):
            cells = [self._clean_text(td.get_text()) for td in tr.find_all("td")]
            if len(cells) <= max(symbol_idx, weight_idx, name_idx or 0):
                continue
            symbol = cells[symbol_idx].upper()
            weight = self._normalize_weight(cells[weight_idx], scale="percent")
            if not symbol or weight is None:
                continue
            holdings.append(
                EtfHolding(
                    symbol=symbol,
                    name=cells[name_idx] if name_idx is not None else "",
                    weight=weight,
                )
            )
        return holdings


SECTOR_DISPLAY_NAMES: dict[str, str] = {
    "realestate": "Real Estate",
    "real_estate": "Real Estate",
    "consumer_cyclical": "Consumer Cyclical",
    "basic_materials": "Basic Materials",
    "consumer_defensive": "Consumer Defensive",
    "technology": "Technology",
    "communication_services": "Communication Services",
    "financial_services": "Financial Services",
    "utilities": "Utilities",
    "industrials": "Industrials",
    "energy": "Energy",
    "healthcare": "Healthcare",
}


class EtfHoldingsService:
    """Load ETF holdings from supported official issuer sources."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "BudgetTerminal/1.0 (+https://github.com/)",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self.providers = (
            IsharesIssuerProvider(self.session),
            SpdrIssuerProvider(self.session),
            InvescoIssuerProvider(self.session),
            VanguardIssuerProvider(self.session),
            FirstTrustIssuerProvider(self.session),
            ProSharesIssuerProvider(self.session),
        )

    def _clean_text(self, value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def _normalize_weight(self, value: Any, *, scale: str = "auto") -> float | None:
        text = self._clean_text(value).replace("%", "").replace(",", "")
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        if scale == "percent":
            return number / 100.0
        if scale == "fraction":
            return number
        return number / 100.0 if abs(number) > 1 else number

    def _format_percent_string(self, value: Any) -> str:
        text = self._clean_text(value).replace(" ", "").rstrip("%")
        if not text:
            return "--"
        try:
            return f"{float(text):.2f}%"
        except ValueError:
            return f"{text}%"

    def _format_large_number(self, value: Any) -> str:
        text = self._clean_text(value).replace("$", "").replace(",", "")
        if not text:
            return "--"
        try:
            number = float(text)
        except ValueError:
            return self._clean_text(value)
        abs_value = abs(number)
        if abs_value >= 1_000_000_000_000:
            return f"{number / 1_000_000_000_000:.2f}T"
        if abs_value >= 1_000_000_000:
            return f"{number / 1_000_000_000:.2f}B"
        if abs_value >= 1_000_000:
            return f"{number / 1_000_000:.2f}M"
        if abs_value >= 1_000:
            return f"{number / 1_000:.2f}K"
        return f"{number:.2f}"

    def load(self, ticker: str) -> EtfHoldingsResult:
        symbol = str(ticker or "").upper().strip()
        if not symbol:
            raise EtfHoldingsError("Ticker is required.")
        errors: list[str] = []
        for provider in self.providers:
            try:
                result = provider.fetch(symbol)
            except requests.RequestException as exc:
                errors.append(f"{provider.issuer}: {exc}")
                continue
            except Exception as exc:
                errors.append(f"{provider.issuer}: {exc}")
                continue
            if result is not None:
                result = self._enrich_with_yfinance(result)
                result.holdings.sort(key=lambda row: row.weight if row.weight is not None else -1.0, reverse=True)
                return result
        fallback = self._load_yfinance_fallback(symbol)
        if fallback is not None:
            return fallback
        if errors:
            raise UnsupportedEtfIssuerError(
                f"Issuer not yet supported for full holdings import. Tried official sources: {', '.join(errors)}"
            )
        raise UnsupportedEtfIssuerError("Issuer not yet supported for full holdings import.")

    def _enrich_with_yfinance(self, result: EtfHoldingsResult) -> EtfHoldingsResult:
        """Supplement issuer-provided result with Yahoo Finance metadata."""
        try:
            with YF_ETF_LOCK:
                ticker_obj = yf.Ticker(result.ticker)
                info = ticker_obj.info or {}
                funds_data = ticker_obj.funds_data
                fund_ops = funds_data.fund_operations.copy()
                sector_weights = funds_data.sector_weightings
        except Exception:
            return result
        if not result.fund_name or result.fund_name == result.ticker:
            name = self._clean_text(info.get("longName") or info.get("shortName"))
            if name:
                result.fund_name = name
        if result.expense_ratio in ("--", ""):
            try:
                expense_value = fund_ops.at["Annual Report Expense Ratio", result.ticker]
                result.expense_ratio = self._format_percent_string(float(expense_value) * 100.0)
            except Exception:
                pass
        if result.net_assets in ("--", ""):
            assets = info.get("totalAssets")
            if assets:
                result.net_assets = self._format_large_number(assets)
        if not result.sector_breakdown and sector_weights:
            try:
                sectors: dict[str, float] = {}
                for entry in sector_weights:
                    if isinstance(entry, dict):
                        for key, value in entry.items():
                            display = SECTOR_DISPLAY_NAMES.get(key, key.replace("_", " ").title())
                            sectors[display] = round(float(value) * 100, 2)
                if sectors:
                    result.sector_breakdown = dict(sorted(sectors.items(), key=lambda x: x[1], reverse=True))
            except Exception:
                pass
        return result

    def _load_yfinance_fallback(self, ticker: str) -> EtfHoldingsResult | None:
        """Fallback to Yahoo Finance top holdings when official issuers are unsupported."""
        try:
            with YF_ETF_LOCK:
                ticker_obj = yf.Ticker(ticker)
                info = ticker_obj.info or {}
                funds_data = ticker_obj.funds_data
                holdings_df = funds_data.top_holdings.copy()
                overview = dict(funds_data.fund_overview or {})
                fund_ops = funds_data.fund_operations.copy()
                sector_weights = funds_data.sector_weightings
        except Exception:
            return None
        if holdings_df is None or getattr(holdings_df, "empty", True):
            return None
        holdings: list[EtfHolding] = []
        frame = holdings_df.reset_index().copy()
        for _, row in frame.iterrows():
            symbol = str(row.get("Symbol", "") or "").upper().strip()
            name = str(row.get("Name", "") or "").strip()
            weight = self._normalize_weight(row.get("Holding Percent"), scale="fraction")
            if not symbol or weight is None:
                continue
            holdings.append(EtfHolding(symbol=symbol, name=name, weight=weight))
        if not holdings:
            return None
        expense_ratio = "--"
        net_assets = "--"
        if fund_ops is not None and not getattr(fund_ops, "empty", True):
            try:
                expense_value = fund_ops.at["Annual Report Expense Ratio", ticker]
                expense_ratio = self._format_percent_string(float(expense_value) * 100.0)
            except Exception:
                pass
            try:
                assets_value = fund_ops.at["Total Net Assets", ticker]
                net_assets = self._format_large_number(assets_value)
            except Exception:
                pass
        family = self._clean_text(overview.get("family"))
        issuer = "Yahoo Finance Top Holdings Fallback"
        if family:
            issuer = f"{issuer} ({family})"
        sectors: dict[str, float] = {}
        if sector_weights:
            try:
                for entry in sector_weights:
                    if isinstance(entry, dict):
                        for key, value in entry.items():
                            display = SECTOR_DISPLAY_NAMES.get(key, key.replace("_", " ").title())
                            sectors[display] = round(float(value) * 100, 2)
                sectors = dict(sorted(sectors.items(), key=lambda x: x[1], reverse=True))
            except Exception:
                pass
        return EtfHoldingsResult(
            ticker=ticker,
            fund_name=self._clean_text(info.get("longName") or info.get("shortName") or ticker),
            issuer=issuer,
            expense_ratio=expense_ratio,
            net_assets=net_assets,
            holdings=holdings,
            sector_breakdown=sectors,
            is_partial=True,
            coverage_note="Yahoo Finance fallback provides a top-holdings list, not the full ETF holdings list.",
        )


def _parse_xlsx_rows(content: bytes) -> list[list[str]]:
    """Read the first worksheet of an xlsx file using stdlib only."""
    namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(content)) as workbook:
        shared_strings = _read_shared_strings(workbook, namespace)
        sheet_name = "xl/worksheets/sheet1.xml"
        if sheet_name not in workbook.namelist():
            return []
        root = ET.fromstring(workbook.read(sheet_name))
    rows: list[list[str]] = []
    for row in root.findall(".//a:sheetData/a:row", namespace):
        values: list[str] = []
        for cell in row.findall("a:c", namespace):
            cell_ref = cell.attrib.get("r", "")
            col_index = _excel_col_to_index(re.sub(r"\d+", "", cell_ref))
            while len(values) < col_index:
                values.append("")
            values.append(_cell_value(cell, shared_strings, namespace))
        rows.append(values)
    return rows


def _read_shared_strings(workbook: zipfile.ZipFile, namespace: dict[str, str]) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []
    root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("a:si", namespace):
        text = "".join(node.text or "" for node in item.findall(".//a:t", namespace))
        values.append(text)
    return values


def _cell_value(cell: ET.Element, shared_strings: list[str], namespace: dict[str, str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//a:t", namespace)).strip()
    value_node = cell.find("a:v", namespace)
    if value_node is None or value_node.text is None:
        return ""
    raw_value = value_node.text
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)]
        except Exception:
            return ""
    return raw_value.strip()


def _excel_col_to_index(label: str) -> int:
    result = 0
    for char in label.upper():
        if "A" <= char <= "Z":
            result = (result * 26) + (ord(char) - ord("A") + 1)
    return max(result - 1, 0)
