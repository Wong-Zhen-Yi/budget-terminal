from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .paths import is_frozen

RUN_ON_STARTUP_VALUE_NAME = 'BudgetTerminal'
_RUN_KEY_PATH = r'Software\Microsoft\Windows\CurrentVersion\Run'

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows platforms
    winreg = None


def _supported_executable_path() -> Path | None:
    """Return the packaged executable path when startup registration is supported."""
    if os.name != 'nt' or winreg is None:
        return None
    if not is_frozen():
        return None
    executable = Path(sys.executable).resolve(strict=False)
    return executable if executable.exists() else None


def _quoted_command(executable_path: Path) -> str:
    """Return the Windows Run command for the packaged executable."""
    return f'"{str(executable_path)}"'


def _extract_command_executable(command: Any) -> str:
    """Extract the executable path from a Run command string."""
    text = str(command or '').strip()
    if not text:
        return ''
    if text.startswith('"'):
        end_quote = text.find('"', 1)
        if end_quote > 1:
            return text[1:end_quote]
    return text.split(' ', 1)[0].strip('"')


def _normalize_path(value: Any) -> str:
    """Normalize one filesystem path for case-insensitive Windows comparisons."""
    text = str(value or '').strip().strip('"')
    if not text:
        return ''
    expanded = os.path.expandvars(os.path.expanduser(text))
    try:
        resolved = Path(expanded).resolve(strict=False)
    except OSError:
        resolved = Path(expanded)
    return os.path.normcase(os.path.normpath(str(resolved)))


def _read_run_value() -> str:
    """Read the current per-user Run entry for Budget Terminal."""
    if winreg is None:
        return ''
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, RUN_ON_STARTUP_VALUE_NAME)
    except FileNotFoundError:
        return ''
    return str(value or '').strip()


def get_startup_registration_status() -> dict[str, Any]:
    """Return the current startup-registration status for the packaged app."""
    executable_path = _supported_executable_path()
    if os.name != 'nt' or winreg is None:
        return {
            'supported': False,
            'enabled': False,
            'message': 'Run on startup is available on Windows only.',
            'expected_command': '',
            'expected_executable': '',
            'registered_command': '',
            'registered_executable': '',
            'registered_for_other_build': False,
        }
    if not is_frozen():
        return {
            'supported': False,
            'enabled': False,
            'message': 'Run on startup is available in packaged Windows builds only.',
            'expected_command': '',
            'expected_executable': '',
            'registered_command': '',
            'registered_executable': '',
            'registered_for_other_build': False,
        }
    if executable_path is None:
        return {
            'supported': False,
            'enabled': False,
            'message': 'Run on startup is unavailable because the packaged executable could not be resolved.',
            'expected_command': '',
            'expected_executable': '',
            'registered_command': '',
            'registered_executable': '',
            'registered_for_other_build': False,
        }
    registered_command = _read_run_value()
    registered_executable = _extract_command_executable(registered_command)
    expected_executable = str(executable_path)
    enabled = bool(registered_command) and _normalize_path(registered_executable) == _normalize_path(expected_executable)
    registered_for_other_build = bool(registered_command) and not enabled
    if enabled:
        message = 'Budget Terminal will launch automatically when you sign in to Windows.'
    elif registered_for_other_build:
        message = (
            'Startup is registered for another Budget Terminal build. '
            'Enabling this here will replace it.'
        )
    else:
        message = 'Budget Terminal will stay closed until you launch it manually.'
    return {
        'supported': True,
        'enabled': enabled,
        'message': message,
        'expected_command': _quoted_command(executable_path),
        'expected_executable': expected_executable,
        'registered_command': registered_command,
        'registered_executable': registered_executable,
        'registered_for_other_build': registered_for_other_build,
    }


def set_run_on_startup(enabled: bool) -> dict[str, Any]:
    """Enable or disable Windows login startup for the packaged executable."""
    status = get_startup_registration_status()
    if not status.get('supported', False):
        raise RuntimeError(str(status.get('message', 'Run on startup is unavailable.')))
    if winreg is None:
        raise RuntimeError('Windows startup registration is unavailable in this environment.')
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH) as key:
            if enabled:
                winreg.SetValueEx(
                    key,
                    RUN_ON_STARTUP_VALUE_NAME,
                    0,
                    winreg.REG_SZ,
                    str(status.get('expected_command', '')),
                )
            else:
                try:
                    winreg.DeleteValue(key, RUN_ON_STARTUP_VALUE_NAME)
                except FileNotFoundError:
                    pass
    except OSError as exc:
        raise RuntimeError(f'Unable to update Windows startup registration: {exc}') from exc
    refreshed = get_startup_registration_status()
    if enabled and not refreshed.get('enabled', False):
        raise RuntimeError('Windows startup registration did not persist for the current Budget Terminal build.')
    if not enabled and refreshed.get('registered_command'):
        raise RuntimeError('Windows startup registration is still present after disabling it.')
    return refreshed
