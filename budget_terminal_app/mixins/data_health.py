from __future__ import annotations

from typing import Any

from budget_terminal_app.compat import *
from budget_terminal_app.data_service.results import market_data_errors, market_data_meta


def _on_gui_thread() -> bool:
    """Return whether the caller is running on the thread that owns the widgets."""
    app = QApplication.instance()
    if app is None:
        return True
    return QThread.currentThread() is app.thread()


class DataHealthMixin:
    """Track market-data freshness and failures for the current app session."""

    _DATA_HEALTH_MAX_EVENTS = 120

    def _init_data_health_state(self) -> None:
        """Initialize in-memory health tracking for this app session."""
        self._data_health_events = []
        self._data_health_missing_tickers = set()
        self._data_health_last_refresh_ts = None

    def _data_health_now(self) -> datetime.datetime:
        """Return a timezone-aware timestamp for user-facing health records."""
        try:
            return self._now_for_clock_country()
        except Exception:
            return datetime.datetime.now().astimezone()

    def _data_health_timestamp_text(self, ts: Any = None) -> str:
        """Format one health timestamp for compact display."""
        value = ts if isinstance(ts, datetime.datetime) else self._data_health_now()
        try:
            return value.strftime('%Y-%m-%d %H:%M:%S %Z').strip()
        except Exception:
            return str(value)

    def _record_data_health_event(
        self,
        subsystem: Any,
        *,
        severity: str = 'warning',
        source: Any = '',
        freshness: Any = '',
        reason: Any = '',
        symbols: Any = None,
        errors: Any = None,
    ) -> None:
        """Store one data-health warning or issue and refresh visible summaries."""
        app = QApplication.instance()
        if app is not None and QThread.currentThread() is not app.thread() and hasattr(self, '_invoke_main'):
            queued_symbols = list(symbols) if isinstance(symbols, (list, tuple, set)) else ([] if symbols is None else [symbols])
            queued_errors = list(errors) if isinstance(errors, (list, tuple, set)) else ([] if errors is None else [errors])
            self._invoke_main.emit(
                lambda: self._record_data_health_event(
                    subsystem,
                    severity=severity,
                    source=source,
                    freshness=freshness,
                    reason=reason,
                    symbols=queued_symbols,
                    errors=queued_errors,
                )
            )
            return
        if not hasattr(self, '_data_health_events'):
            self._init_data_health_state()
        cleaned_symbols = []
        symbol_items = list(symbols) if isinstance(symbols, (list, tuple, set)) else ([] if symbols is None else [symbols])
        for symbol in symbol_items:
            text = str(symbol or '').upper().strip()
            if text and text not in cleaned_symbols:
                cleaned_symbols.append(text)
        normalized_errors = []
        error_items = list(errors) if isinstance(errors, (list, tuple, set)) else ([] if errors is None else [errors])
        for error in error_items:
            if isinstance(error, dict):
                text = str(error.get('reason') or error.get('message') or '').strip()
                operation = str(error.get('operation') or '').strip()
                error_symbol = str(error.get('symbol') or '').upper().strip()
                pieces = [piece for piece in (operation, error_symbol, text) if piece]
                if pieces:
                    normalized_errors.append(' | '.join(pieces))
            else:
                text = str(error or '').strip()
                if text:
                    normalized_errors.append(text)
        clean_reason = str(reason or '').strip()
        if not clean_reason and normalized_errors:
            clean_reason = normalized_errors[0]
        event = {
            'timestamp': self._data_health_now(),
            'severity': 'issue' if str(severity).lower() in ('issue', 'negative', 'failed') else 'warning',
            'subsystem': str(subsystem or 'Market data').strip(),
            'source': str(source or '').strip(),
            'freshness': str(freshness or '').strip().lower(),
            'reason': clean_reason or 'Market data health warning.',
            'symbols': cleaned_symbols,
            'errors': normalized_errors[:5],
            'error_count': len(normalized_errors),
            'active': True,
            'resolved_at': None,
        }
        fingerprint = (
            event['severity'],
            event['subsystem'],
            event['source'],
            event['freshness'],
            event['reason'],
            tuple(event['symbols']),
            tuple(event['errors']),
        )
        for existing in reversed(self._data_health_events[-5:]):
            existing_fingerprint = (
                existing.get('severity'),
                existing.get('subsystem'),
                existing.get('source'),
                existing.get('freshness'),
                existing.get('reason'),
                tuple(existing.get('symbols') or []),
                tuple(existing.get('errors') or []),
            )
            if existing_fingerprint != fingerprint or not bool(existing.get('active', True)):
                continue
            existing_ts = existing.get('timestamp')
            try:
                age_seconds = abs((event['timestamp'] - existing_ts).total_seconds())
            except Exception:
                age_seconds = 0.0
            if age_seconds <= 5.0:
                logger.info(
                    'Duplicate data health %s skipped for %s: %s',
                    event['severity'],
                    event['subsystem'],
                    event['reason'],
                )
                self._refresh_data_health_views()
                return
        self._data_health_events.append(event)
        overflow = len(self._data_health_events) - int(getattr(self, '_DATA_HEALTH_MAX_EVENTS', 120))
        if overflow > 0:
            del self._data_health_events[:overflow]
        logger.info(
            'Data health %s recorded for %s: %s',
            event['severity'],
            event['subsystem'],
            event['reason'],
        )
        self._refresh_data_health_views()

    def _resolve_data_health_events(self, subsystem: Any, *, symbols: Any = None) -> int:
        """Resolve active events covered by one fresh subsystem result."""
        subsystem_text = str(subsystem or 'Market data').strip()
        symbol_items = list(symbols) if isinstance(symbols, (list, tuple, set)) else ([] if symbols is None else [symbols])
        success_symbols = {str(symbol or '').upper().strip() for symbol in symbol_items if str(symbol or '').strip()}
        resolved_at = self._data_health_now()
        resolved_count = 0
        for event in list(getattr(self, '_data_health_events', []) or []):
            if not bool(event.get('active', True)) or str(event.get('subsystem') or '').strip() != subsystem_text:
                continue
            event_symbols = {str(symbol or '').upper().strip() for symbol in list(event.get('symbols') or []) if str(symbol or '').strip()}
            if success_symbols and event_symbols and not event_symbols.issubset(success_symbols):
                continue
            event['active'] = False
            event['resolved_at'] = resolved_at
            resolved_count += 1
        if resolved_count:
            logger.info('Resolved %s data health event(s) for %s.', resolved_count, subsystem_text)
            self._refresh_data_health_views()
        return resolved_count

    def _record_data_health_payload(
        self,
        subsystem: Any,
        payload: Any,
        *,
        symbols: Any = None,
        expected_symbols: Any = None,
    ) -> None:
        """Inspect a market-data payload for stale/partial/failed metadata and missing prices."""
        if not isinstance(payload, dict) and not hasattr(payload, '_market_data_meta'):
            return
        meta = market_data_meta(payload)
        errors = market_data_errors(payload)
        freshness = str(meta.get('freshness') or 'fresh').strip().lower()
        source = str(meta.get('source') or '').strip()
        failure_reason = str(meta.get('failure_reason') or '').strip()
        if freshness in ('stale', 'partial', 'failed') or errors:
            severity = 'issue' if freshness == 'failed' else 'warning'
            self._record_data_health_event(
                subsystem,
                severity=severity,
                source=source,
                freshness=freshness,
                reason=failure_reason,
                symbols=symbols,
                errors=errors,
            )
        if freshness == 'fresh':
            self._resolve_data_health_events(subsystem, symbols=symbols)
        self._record_data_health_missing_prices(subsystem, payload, expected_symbols=expected_symbols)

    def _record_data_health_missing_prices(self, subsystem: Any, payload: Any, *, expected_symbols: Any = None) -> None:
        """Record portfolio tickers that are missing usable prices in a payload."""
        if not isinstance(payload, dict):
            return
        expected = []
        for symbol in list(expected_symbols or []):
            text = str(symbol or '').upper().strip()
            if text and text not in expected:
                expected.append(text)
        if not expected:
            return
        quote_map = payload.get('portfolio', {}) if isinstance(payload.get('portfolio', {}), dict) else {}
        missing = []
        recovered = []
        for symbol in expected:
            quote = quote_map.get(symbol, {})
            price = quote.get('price') if isinstance(quote, dict) else None
            try:
                numeric = float(price)
            except (TypeError, ValueError):
                numeric = 0.0
            if numeric <= 0:
                missing.append(symbol)
            else:
                recovered.append(symbol)
        if hasattr(self, '_data_health_missing_tickers') and recovered:
            before_recovery = set(self._data_health_missing_tickers)
            self._data_health_missing_tickers.difference_update(recovered)
            if set(self._data_health_missing_tickers) != before_recovery:
                self._refresh_data_health_views()
        if not missing:
            self._resolve_data_health_events(subsystem, symbols=expected)
            return
        if not hasattr(self, '_data_health_missing_tickers'):
            self._data_health_missing_tickers = set()
        before = set(self._data_health_missing_tickers)
        self._data_health_missing_tickers.update(missing)
        if set(self._data_health_missing_tickers) == before:
            return
        self._record_data_health_event(
            subsystem,
            severity='warning',
            source='portfolio quotes',
            freshness='partial',
            reason=f'Missing usable prices for {len(missing)} portfolio ticker(s).',
            symbols=missing,
        )

    def _record_data_health_exception(self, subsystem: Any, error: Any, *, symbols: Any = None, severity: str = 'issue') -> None:
        """Record an exception or explicit failure as a health event."""
        self._record_data_health_event(
            subsystem,
            severity=severity,
            source='runtime',
            freshness='failed' if severity == 'issue' else 'partial',
            reason=str(error or 'Market data request failed.'),
            symbols=symbols,
        )

    def _record_data_health_fallback(self, subsystem: Any, error: Any, *, symbols: Any = None) -> None:
        """Record an API/service fallback that still continued with another path."""
        self._record_data_health_event(
            subsystem,
            severity='warning',
            source='embedded data service',
            freshness='partial',
            reason=f'Embedded data service fallback used: {error}',
            symbols=symbols,
        )

    def _data_health_counts(self) -> tuple[int, int]:
        """Return issue and warning counts for the current session."""
        events = [event for event in list(getattr(self, '_data_health_events', []) or []) if bool(event.get('active', True))]
        issue_count = sum(1 for event in events if event.get('severity') == 'issue')
        warning_count = max(len(events) - issue_count, 0)
        return issue_count, warning_count

    def _data_health_summary(self) -> tuple[str, str]:
        """Return user-facing data-health summary text and status."""
        issue_count, warning_count = self._data_health_counts()
        if issue_count > 0:
            suffix = 'issue' if issue_count == 1 else 'issues'
            return f'Data health: {issue_count} {suffix}', 'negative'
        if warning_count > 0:
            suffix = 'warning' if warning_count == 1 else 'warnings'
            return f'Data health: {warning_count} {suffix}', 'warning'
        return 'Data health: OK', 'positive'

    def _refresh_data_health_views(self) -> None:
        """Refresh footer and Settings health widgets if they exist.

        This is the only place data-health touches widgets, so the GUI-thread guard lives here
        rather than at each caller. Background fetches reach it through
        ``_record_data_health_payload`` -> ``_resolve_data_health_events`` /
        ``_record_data_health_missing_prices``, from pool threads and the startup warmup threads.
        ``set_status_text`` calls ``setStyleSheet``, which re-polishes and repaints the widget --
        doing that off the GUI thread corrupts Qt's state and aborts the process later, with the
        access violation surfacing inside ``app.exec()`` and no Python frame to blame.
        """
        if not _on_gui_thread():
            invoke_main = getattr(self, '_invoke_main', None)
            if invoke_main is not None:
                try:
                    invoke_main.emit(self._refresh_data_health_views)
                except RuntimeError:
                    logger.debug('Window closed before a data-health refresh could be marshalled.')
                return
            # Without the marshalling channel, skipping the repaint is the only safe option.
            logger.debug('Skipping off-thread data-health refresh; no main-thread channel.')
            return
        summary, status = self._data_health_summary()
        self._data_health_last_refresh_ts = self._data_health_now()
        if hasattr(self, 'data_health_label'):
            self.set_status_text(self.data_health_label, summary, status=status)
        if hasattr(self, 'settings_data_health_summary_label'):
            self.set_status_text(self.settings_data_health_summary_label, summary, status=status)
        if hasattr(self, 'settings_data_health_report'):
            self.settings_data_health_report.setPlainText(self._build_data_health_report())

    def _build_data_health_report(self) -> str:
        """Build a copyable text report for the Settings page."""
        if not hasattr(self, '_data_health_events'):
            self._init_data_health_state()
        summary, _status = self._data_health_summary()
        lines = [
            'Budget Terminal Data Health Report',
            f'Generated: {self._data_health_timestamp_text()}',
            f'Summary: {summary}',
        ]
        if getattr(self, '_data_collection_ts', None):
            try:
                collected_dt = datetime.datetime.fromtimestamp(
                    float(self._data_collection_ts),
                    tz=self._get_clock_tzinfo(),
                )
                lines.append(f'Latest data collection: {self._data_health_timestamp_text(collected_dt)}')
            except Exception:
                lines.append('Latest data collection: unavailable')
        sources = ', '.join(getattr(self, '_data_collection_sources', []) or [])
        lines.append(f'Latest sources: {sources or "unknown"}')
        missing = sorted(getattr(self, '_data_health_missing_tickers', set()) or [])
        lines.append(f'Missing price tickers: {", ".join(missing) if missing else "none"}')
        lines.append('')
        events = list(getattr(self, '_data_health_events', []) or [])
        if not events:
            lines.append('No stale, partial, failed, or fallback market-data events have been recorded this session.')
            return '\n'.join(lines)
        lines.append(f'Recent events ({len(events)} stored):')
        for event in reversed(events[-40:]):
            symbols = ', '.join(event.get('symbols') or [])
            source = str(event.get('source') or 'unknown')
            freshness = str(event.get('freshness') or 'n/a')
            active = bool(event.get('active', True))
            state = 'ACTIVE' if active else f'RESOLVED {self._data_health_timestamp_text(event.get("resolved_at"))}'
            line = (
                f'- [{self._data_health_timestamp_text(event.get("timestamp"))}] '
                f'{state} | '
                f'{str(event.get("severity") or "warning").upper()} | '
                f'{event.get("subsystem") or "Market data"} | '
                f'{freshness} | {source} | {event.get("reason") or ""}'
            )
            if symbols:
                line = f'{line} | Symbols: {symbols}'
            error_count = int(event.get('error_count', 0) or 0)
            if error_count:
                line = f'{line} | Errors: {error_count}'
            lines.append(line)
            for detail in list(event.get('errors') or [])[:3]:
                lines.append(f'  error: {detail}')
        return '\n'.join(lines)
