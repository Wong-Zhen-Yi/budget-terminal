# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Setup (Windows, PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip==26.1.2 setuptools==83.0.0
.\.venv\Scripts\python.exe -m pip install --upgrade --upgrade-strategy eager -r requirements.txt -r requirements-dev.txt
```

Run the app:

```powershell
python budget_terminal.py
```

Checks (run the ones matching what you touched):

```powershell
.\.venv\Scripts\python.exe -m ruff check budget_terminal.py budget_terminal_app scripts
.\.venv\Scripts\python.exe -m compileall -q budget_terminal.py budget_terminal_app
.\.venv\Scripts\python.exe scripts\test_public_repo_privacy.py
```

Run one smoke test — each `scripts/test_*.py` is a standalone module with a `__main__` block,
not a pytest file. There is no pytest suite; do not add pytest invocations.

```powershell
.\.venv\Scripts\python.exe scripts\test_data_service_transport.py
```

Anything that constructs Qt widgets needs an offscreen platform when run headless:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'; .\.venv\Scripts\python.exe scripts\test_refresh_responsiveness.py
```

`.github/workflows/python-ci.yml` is the authoritative list of which smoke tests gate a merge —
mirror that subset locally before pushing. Windows exe build: `.\packaging\build_exe.bat`
(see `packaging/PACKAGING.md`).

## Architecture

### Startup

`budget_terminal.py` re-execs itself through `.venv\Scripts\python.exe` when that exists
(suppress with `BUDGET_TERMINAL_SKIP_LOCAL_VENV=1`), configures DPI awareness and persistent error
logging, then calls `budget_terminal_app.main.main()`.

`main.py` enforces a minimum `yfinance` version, creates the `QApplication` (Fusion style), shows
`StartupLoadingScreen`, imports `BudgetTerminalApp`, runs `_prepare_startup_before_show()` while the
window is hidden, then shows it. A 30s timer force-shows the window if preparation stalls. Each
launch is an independent process; multiple windows share the same on-disk state.

### The main window is one mixin composition

`budget_terminal_app/app.py` defines `BudgetTerminalApp` as a single class inheriting ~45 mixins
from `budget_terminal_app/mixins/` plus `QMainWindow`. There is no per-page widget class — a "page"
is a mixin contributing an `init_page<N>()` builder plus refresh and render methods to one shared
window object. Adding or removing a page means editing the MRO in `app.py`.

Two numbering schemes coexist. The **stacked-widget index** is what `_PAGE_LABELS`, the refresh
routes, and navigation order use. The **legacy page number N** is what widget attributes
(`page4`), builders (`init_page4`), and method prefixes (`_p4_*`) use. They do not match: Portfolio
is stacked index 1 / `page4`, Charts is index 9 / `page10`, News is index 33 / `page34`. Follow the
prefix already used in the file you are editing.

### `_lazy_page_specs()` is the authoritative page table

`WindowSetupMixin._lazy_page_specs()` (`mixins/window_setup.py`) maps each stacked index to its
`page_attr`, `init_method`, `theme_hook`, and optional `hydrate_hook` — this is where you look up
which legacy number a page uses. Only the Dashboard is built eagerly in `init_ui()`; everything else
gets a placeholder widget and is constructed on demand, forced via `_ensure_page_initialized(index)`.
Entries marked `placeholder_only` are retired slots that keep later indexes stable — do not reuse them.

Three more registries must agree with it:

- `WindowSetupMixin._PAGE_LABELS` (`mixins/window_setup.py`) — index to display name
- `REFRESH_ROUTE_ARCHITECTURE` and `REFRESH_ROUTE_CLASSIFICATION` (`mixins/window_lifecycle.py`) —
  index to refresh strategy (`local-only`, `background-coordinated`, `background-single-flight`,
  `background-active-subtab`)
- `DEFAULT_NAVIGATION_PAGE_ORDER` (`persistence.py`) — user-visible tab order

`scripts/test_refresh_route_inventory.py` asserts that the label set and the route-architecture set
are identical, and that every classified route actually dispatches an action from
`_refresh_current_page()`. Register a new page everywhere or that test fails.

### Data flow

```
page mixin  ->  self._data_service_client  ->  DashboardFetchCoordinator  ->  workers/*  ->  CacheManager (sqlite)
                     (may be None)                  (coalescing)             (yfinance etc.)
```

- `data_service/runtime.py` picks the transport from `BUDGET_TERMINAL_DATA_TRANSPORT`: `inprocess`
  (default, no serialization or socket) or `http` (private FastAPI/Uvicorn on localhost, for
  diagnostics). Both satisfy `DataServiceClientProtocol` in `data_service/client.py`, and
  `scripts/test_data_service_transport.py` asserts the two transports return equivalent payloads.
- **The client is attached asynchronously after first paint** (`_start_data_service_async` in
  `main.py`). `self._data_service_client` is `None` during early startup and stays `None` if the
  service fails to start. Mixins must tolerate that — the established pattern is
  `getattr(self, '_data_service_client', None)` plus a direct-worker fallback; see
  `_dashboard_wait_for_data_service_client` in `mixins/dashboard.py`.
- `data_service/coordinator.py` coalesces identical in-flight requests by a normalized key, so two
  pages asking for the same tickers cause one upstream fetch.
- `workers/` classes are `QObject`s exposing `finished = Signal(object)` / `error = Signal(str)`,
  moved onto a `QThread`. Long-running work belongs here, never on the GUI thread.
  Declare container payloads as `Signal(object)`, never `Signal(dict)` or `Signal(list)`: PySide6
  marshals those through `QVariantMap`/`QVariantList`, which copies the payload and silently turns a
  dict with non-string keys into `{}`. `object` passes the Python payload through untouched.
- **Every Yahoo request is paced by one process-wide gate**, installed on yfinance's HTTP session by
  `services/yahoo_rate_limit.py`. yfinance 1.5.2 has no pacing of its own (`network.retries = 0`) and
  raises `YFRateLimitError` on 429. The gate smooths bursts to a sustained rate, caps in-flight
  requests, and on any 429 halves the rate and starts an exponential cooldown, recovering after a
  run of clean responses. Tune it with `BUDGET_TERMINAL_YF_REQUESTS_PER_SECOND`, `_BURST`,
  `_MAX_CONCURRENCY`, `_COOLDOWN_SECONDS`; `BUDGET_TERMINAL_YF_RATE_LIMIT=0` disables it.
  It is installed by the `on_load` hook on the `yf` lazy proxy in `dependencies.py`, so **reach
  yfinance through `from ..dependencies import yf`, never `import yfinance`** — a direct import
  bypasses the gate. `YF_LOCK` still serializes multi-step ticker interactions, but it is a mutex,
  not a rate limiter, and `yf.download(threads=True)` fans out beneath it; do not treat it as
  throttling.
- `services/` is deliberately Qt-free and presentation-independent. Put testable calculation and
  data-shaping logic there — that is what the smoke tests import directly.

### Refresh single-flight

`services/refresh_control.py` provides `RefreshCoordinator`, a Qt-free token-based single-flight
gate: `request(key, signature) -> (token, should_start)` keeps one active request and at most one
pending rerun per page, so rapid user input collapses to the latest state. Call `complete(token)`
for every launched token including failures, and check `is_current(token)` before rendering a
result. The window creates `self._refresh_coordinator` in `mixins/window_bootstrap.py`; page mixins
lazily reuse it via `getattr(self, '_refresh_coordinator', None)`.

### Shared infrastructure

- `dependencies.py` — the common import surface, star-imported by ~17 modules
  (`from ..dependencies import *`). It re-exports the Qt symbols and wraps `pandas`, `pyqtgraph`,
  `requests`, and `yfinance` in `_LazyModuleProxy` so those heavy imports happen on first attribute
  access rather than at startup. Do not import them directly at module top level in hot-path
  modules, and do not "clean up" the star imports — ruff ignores `F403`/`F405` for this.
  It also sets `PYQTGRAPH_QT_LIB=PySide6` before the proxy loads: pyqtgraph probes `PyQt6` ahead of
  `PySide6`, and letting it pick would put a second Qt binding in the process. Qt symbols come from
  `PySide6` — use `Signal`/`Slot`, never the PyQt spellings.
- `paths.py` — resolves every writable location (`%LOCALAPPDATA%\BudgetTerminal`,
  `Documents\Budget Terminal User Data`) and read-only bundled resources via `resource_path()`,
  which is PyInstaller-aware. Never write beside the executable, and do not derive user-data paths
  from `__file__`.
- `cache.py` — `CacheManager` over a single sqlite DB: per-(ticker, interval) DataFrame tables,
  options chains, and a generic namespaced `json_payload_cache`. Table names are sanitized and
  hash-suffixed; use the existing helpers rather than interpolating identifiers into SQL.
- `persistence.py` — all JSON-backed user settings, portfolio state, defaults, and their
  normalizers. New persisted settings go here with a `DEFAULT_*` constant and a normalizer.

## Constraints

- Python 3.11 target; ruff `line-length = 120`, `select = ["E4", "E7", "E9", "F"]`.
- Runtime dependencies are exactly pinned in `requirements.txt`, and `main.py` hard-fails startup
  below `yfinance` 1.5.2. Changing a pin means updating `requirements.txt` and re-running the smoke
  tests, not just installing locally.
- `scripts/test_public_repo_privacy.py` runs first in CI and scans every git-tracked file for
  absolute user home directories, email addresses, the maintainer's name, and credential-shaped
  strings. Keep paths repo-relative in code, docs, and tests.
- `build/`, `dist/`, and `release/` are generated output; treat them as read-only unless the task is
  packaging.
- See `AGENTS.md` for commit/PR conventions and naming style.
