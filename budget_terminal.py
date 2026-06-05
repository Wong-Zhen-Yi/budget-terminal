"""Launch the Budget Terminal desktop application."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_LOCAL_VENV_SKIP_ENV = 'BUDGET_TERMINAL_SKIP_LOCAL_VENV'
_LOCAL_VENV_REEXEC_ENV = 'BUDGET_TERMINAL_LOCAL_VENV_REEXECED'


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name, '')).strip().lower() in {'1', 'true', 'yes', 'on'}


def _same_executable(left: Path, right: Path) -> bool:
    try:
        return os.path.normcase(str(left.resolve(strict=False))) == os.path.normcase(str(right.resolve(strict=False)))
    except OSError:
        return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _local_venv_python() -> Path | None:
    scripts_dir = 'Scripts' if os.name == 'nt' else 'bin'
    executable_name = 'python.exe' if os.name == 'nt' else 'python'
    candidate = Path(__file__).resolve().parent.joinpath('.venv', scripts_dir, executable_name)
    return candidate if candidate.exists() else None


def _maybe_reexec_from_local_venv() -> int | None:
    if getattr(sys, 'frozen', False):
        return None
    if _truthy_env(_LOCAL_VENV_SKIP_ENV) or _truthy_env(_LOCAL_VENV_REEXEC_ENV):
        return None
    venv_python = _local_venv_python()
    if venv_python is None:
        return None
    current_python = Path(sys.executable)
    if _same_executable(current_python, venv_python):
        return None
    env = dict(os.environ)
    env[_LOCAL_VENV_REEXEC_ENV] = '1'
    return subprocess.call([str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]], env=env)


if __name__ == "__main__":
    reexec_return_code = _maybe_reexec_from_local_venv()
    if reexec_return_code is not None:
        raise SystemExit(reexec_return_code)

from budget_terminal_app.dpi import configure_process_dpi_awareness

configure_process_dpi_awareness()

from budget_terminal_app.error_logging import configure_error_logging

configure_error_logging()

try:
    from budget_terminal_app.main import main
except ModuleNotFoundError as exc:
    import logging

    logging.getLogger(__name__).exception('Budget Terminal startup dependency import failed.')
    missing_module = exc.name or "a required package"
    raise SystemExit(
        "Missing dependency: "
        f"{missing_module}\n"
        "Install project requirements with:\n"
        "python -m pip install -r requirements.txt"
    ) from exc

if __name__ == "__main__":
    raise SystemExit(main())
