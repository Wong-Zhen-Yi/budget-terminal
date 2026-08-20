from __future__ import annotations

import datetime
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable

from .dependencies import QObject, logger, Signal, requests
from .paths import is_frozen, user_data_path


LATEST_RELEASE_API_URL = 'https://api.github.com/repos/Wong-Zhen-Yi/budget-terminal/releases/latest'
RELEASES_URL = 'https://github.com/Wong-Zhen-Yi/budget-terminal/releases'
UPDATE_DIR_NAME = 'updates'
HTTP_TIMEOUT_SECONDS = 20
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
UPDATE_WAIT_TIMEOUT_SECONDS = 90
APP_ASSET_PREFIX = 'BudgetTerminal-v'
APP_ASSET_SUFFIX = '.exe'


def normalize_version(value: Any) -> str:
    """Return a compact Budget Terminal version string without a leading tag prefix."""
    text = str(value or '').strip()
    if text.lower().startswith('refs/tags/'):
        text = text.rsplit('/', 1)[-1]
    return text[1:].strip() if text.lower().startswith('v') else text


def version_key(value: Any) -> tuple[int, ...]:
    """Return a numeric key suitable for this project's v0.xxx release tags."""
    normalized = normalize_version(value)
    parts = [int(part) for part in re.findall(r'\d+', normalized)]
    return tuple(parts or [0])


def is_newer_version(latest_version: Any, current_version: Any) -> bool:
    """Return whether latest_version should be treated as newer than current_version."""
    latest = version_key(latest_version)
    current = version_key(current_version)
    width = max(len(latest), len(current))
    latest = latest + (0,) * (width - len(latest))
    current = current + (0,) * (width - len(current))
    return latest > current


def _headers(current_version: str = '') -> dict[str, str]:
    version = normalize_version(current_version) or 'unknown'
    return {
        'Accept': 'application/vnd.github+json',
        'User-Agent': f'BudgetTerminal/{version}',
    }


def _asset_download_url(asset: Any) -> str:
    if not isinstance(asset, dict):
        return ''
    return str(asset.get('browser_download_url') or asset.get('url') or '').strip()


def select_windows_exe_asset(release_payload: dict[str, Any], latest_version: str) -> dict[str, Any] | None:
    """Select the one-file Windows EXE asset from a GitHub release payload."""
    assets = release_payload.get('assets') if isinstance(release_payload, dict) else []
    if not isinstance(assets, list):
        return None
    expected_name = f'{APP_ASSET_PREFIX}{normalize_version(latest_version)}{APP_ASSET_SUFFIX}'.lower()
    exe_assets = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get('name') or '').strip()
        if not name or not name.lower().endswith(APP_ASSET_SUFFIX):
            continue
        if not name.lower().startswith(APP_ASSET_PREFIX.lower()):
            continue
        if not _asset_download_url(asset):
            continue
        if name.lower() == expected_name:
            return dict(asset)
        exe_assets.append(dict(asset))
    return exe_assets[0] if len(exe_assets) == 1 else None


def build_update_check_result(current_version: str, release_payload: dict[str, Any]) -> dict[str, Any]:
    """Build a normalized update-check result from a GitHub release payload."""
    current = normalize_version(current_version)
    payload = release_payload if isinstance(release_payload, dict) else {}
    if payload.get('draft') or payload.get('prerelease'):
        return {
            'ok': False,
            'current_version': current,
            'latest_version': '',
            'latest_tag': '',
            'update_available': False,
            'asset': None,
            'release_url': RELEASES_URL,
            'message': 'Latest release is not a stable public release.',
            'checked_at': datetime.datetime.now().isoformat(timespec='seconds'),
        }
    latest_tag = str(payload.get('tag_name') or payload.get('name') or '').strip()
    latest_version = normalize_version(latest_tag)
    if not latest_version:
        return {
            'ok': False,
            'current_version': current,
            'latest_version': '',
            'latest_tag': latest_tag,
            'update_available': False,
            'asset': None,
            'release_url': str(payload.get('html_url') or RELEASES_URL),
            'message': 'Latest release did not include a version tag.',
            'checked_at': datetime.datetime.now().isoformat(timespec='seconds'),
        }
    update_available = is_newer_version(latest_version, current)
    asset = select_windows_exe_asset(payload, latest_version) if update_available else None
    if update_available and asset is None:
        return {
            'ok': False,
            'current_version': current,
            'latest_version': latest_version,
            'latest_tag': latest_tag,
            'update_available': True,
            'asset': None,
            'release_url': str(payload.get('html_url') or RELEASES_URL),
            'message': f'Budget Terminal v{latest_version} is available, but no Windows EXE asset was found.',
            'checked_at': datetime.datetime.now().isoformat(timespec='seconds'),
        }
    message = (
        f'Budget Terminal v{latest_version} is available.'
        if update_available
        else f'Budget Terminal is up to date at v{current}.'
    )
    return {
        'ok': True,
        'current_version': current,
        'latest_version': latest_version,
        'latest_tag': latest_tag,
        'update_available': update_available,
        'asset': asset,
        'release_url': str(payload.get('html_url') or RELEASES_URL),
        'message': message,
        'checked_at': datetime.datetime.now().isoformat(timespec='seconds'),
    }


def check_for_update(current_version: str) -> dict[str, Any]:
    """Fetch the latest stable GitHub release and compare it with current_version."""
    current = normalize_version(current_version)
    try:
        response = requests.get(
            LATEST_RELEASE_API_URL,
            headers=_headers(current),
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        return build_update_check_result(current, payload)
    except Exception as exc:
        logger.exception('Budget Terminal update check failed.')
        return {
            'ok': False,
            'current_version': current,
            'latest_version': '',
            'latest_tag': '',
            'update_available': False,
            'asset': None,
            'release_url': RELEASES_URL,
            'message': f'Unable to check for updates: {exc}',
            'checked_at': datetime.datetime.now().isoformat(timespec='seconds'),
        }


def packaged_update_status() -> dict[str, Any]:
    """Return whether this process can install packaged Windows updates."""
    if os.name != 'nt':
        return {
            'supported': False,
            'message': 'Self-update install is available on Windows packaged builds only.',
            'executable_path': '',
        }
    if not is_frozen():
        return {
            'supported': False,
            'message': 'Self-update install is available in packaged Windows builds only.',
            'executable_path': '',
        }
    executable = Path(sys.executable).resolve(strict=False)
    if not executable.exists():
        return {
            'supported': False,
            'message': 'Self-update is unavailable because the packaged executable could not be resolved.',
            'executable_path': str(executable),
        }
    return {
        'supported': True,
        'message': 'Packaged Windows self-update is available.',
        'executable_path': str(executable),
    }


def updates_dir() -> Path:
    """Return the writable update staging directory."""
    path = user_data_path(UPDATE_DIR_NAME)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_asset_name(asset_name: Any) -> str:
    name = Path(str(asset_name or '')).name.strip()
    if not name.lower().endswith(APP_ASSET_SUFFIX):
        return f'{APP_ASSET_PREFIX}update{APP_ASSET_SUFFIX}'
    return name


def _expected_sha256(expected_digest: Any) -> str:
    text = str(expected_digest or '').strip().lower()
    if not text:
        return ''
    if text.startswith('sha256:'):
        text = text.split(':', 1)[1].strip()
    if re.fullmatch(r'[0-9a-f]{64}', text):
        return text
    return ''


def _format_download_progress(downloaded_bytes: int, expected_size: int) -> str:
    downloaded_mb = downloaded_bytes / (1024 * 1024)
    if expected_size > 0:
        total_mb = expected_size / (1024 * 1024)
        return f'Downloading update... {downloaded_mb:.1f}/{total_mb:.1f} MB'
    return f'Downloading update... {downloaded_mb:.1f} MB'


def download_update(
    asset_url: str,
    expected_digest: Any,
    target_dir: str | Path,
    *,
    expected_size: Any = None,
    asset_name: Any = None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Download and verify a packaged EXE update asset."""
    url = str(asset_url or '').strip()
    if not url:
        raise RuntimeError('Update asset URL is missing.')
    target_root = Path(target_dir)
    target_root.mkdir(parents=True, exist_ok=True)
    target_path = target_root / _safe_asset_name(asset_name)
    temp_path = target_path.with_suffix(target_path.suffix + '.download')
    expected_hash = _expected_sha256(expected_digest)
    try:
        expected_size_int = int(expected_size or 0)
    except (TypeError, ValueError):
        expected_size_int = 0

    if temp_path.exists():
        temp_path.unlink()
    sha256 = hashlib.sha256()
    downloaded = 0
    last_status_mb = -1
    response = requests.get(
        url,
        headers=_headers(),
        stream=True,
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    try:
        response.raise_for_status()
        with temp_path.open('wb') as handle:
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                if not chunk:
                    continue
                handle.write(chunk)
                sha256.update(chunk)
                downloaded += len(chunk)
                current_mb = downloaded // DOWNLOAD_CHUNK_BYTES
                if progress_callback is not None and current_mb != last_status_mb:
                    last_status_mb = current_mb
                    progress_callback(_format_download_progress(downloaded, expected_size_int))
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            logger.debug('Unable to remove failed update download %s.', temp_path, exc_info=True)
        raise
    finally:
        close = getattr(response, 'close', None)
        if callable(close):
            close()

    digest = sha256.hexdigest()
    if expected_size_int > 0 and downloaded != expected_size_int:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f'Downloaded update size mismatch: expected {expected_size_int} bytes, got {downloaded}.')
    if expected_hash and digest.lower() != expected_hash:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError('Downloaded update failed SHA256 verification.')

    temp_path.replace(target_path)
    return {
        'ok': True,
        'path': str(target_path),
        'bytes': downloaded,
        'sha256': digest,
        'digest_verified': bool(expected_hash),
        'message': 'Update downloaded and verified.',
    }


def _assert_directory_writable(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    probe_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix='budget-terminal-update-', suffix='.tmp', dir=directory, delete=False) as probe:
            probe_path = Path(probe.name)
            probe.write(b'probe')
    except Exception as exc:
        raise RuntimeError(f'Packaged app folder is not writable: {directory}') from exc
    finally:
        if probe_path is not None:
            try:
                probe_path.unlink(missing_ok=True)
            except Exception:
                logger.debug('Unable to remove update write probe %s.', probe_path, exc_info=True)


def _updater_script_text() -> str:
    return r'''param(
    [int]$ProcessId,
    [string]$TargetPath,
    [string]$DownloadPath,
    [string]$BackupPath,
    [string]$LogPath,
    [int]$WaitTimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'

function Write-UpdateLog {
    param([string]$Message)
    $dir = Split-Path -Parent $LogPath
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -LiteralPath $LogPath -Value $line
}

try {
    Write-UpdateLog "Updater started for process $ProcessId"
    $deadline = (Get-Date).AddSeconds($WaitTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if ($null -eq $proc) {
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
        throw "Budget Terminal did not exit within $WaitTimeoutSeconds seconds."
    }
    if (-not (Test-Path -LiteralPath $DownloadPath -PathType Leaf)) {
        throw "Downloaded update was not found: $DownloadPath"
    }
    if (Test-Path -LiteralPath $BackupPath -PathType Leaf) {
        Remove-Item -LiteralPath $BackupPath -Force
    }
    if (Test-Path -LiteralPath $TargetPath -PathType Leaf) {
        Move-Item -LiteralPath $TargetPath -Destination $BackupPath -Force
        Write-UpdateLog "Backed up current executable to $BackupPath"
    }
    Move-Item -LiteralPath $DownloadPath -Destination $TargetPath -Force
    Write-UpdateLog "Installed update to $TargetPath"
    Start-Process -FilePath $TargetPath
    Write-UpdateLog "Restarted Budget Terminal"
    exit 0
} catch {
    Write-UpdateLog ("Update failed: " + $_.Exception.Message)
    try {
        if ((-not (Test-Path -LiteralPath $TargetPath -PathType Leaf)) -and (Test-Path -LiteralPath $BackupPath -PathType Leaf)) {
            Move-Item -LiteralPath $BackupPath -Destination $TargetPath -Force
            Write-UpdateLog "Restored backup executable"
            Start-Process -FilePath $TargetPath
        }
    } catch {
        Write-UpdateLog ("Backup restore failed: " + $_.Exception.Message)
    }
    exit 1
}
'''


def launch_packaged_update(
    downloaded_exe_path: str | Path,
    *,
    latest_version: str,
    release_url: str = '',
    target_executable: str | Path | None = None,
) -> dict[str, Any]:
    """Launch a detached updater that replaces the running packaged executable."""
    status = packaged_update_status()
    if not status.get('supported', False) and target_executable is None:
        raise RuntimeError(str(status.get('message') or 'Packaged update is unavailable.'))
    target_path = Path(target_executable or status.get('executable_path') or '').resolve(strict=False)
    download_path = Path(downloaded_exe_path).resolve(strict=False)
    if not target_path:
        raise RuntimeError('Current packaged executable path is unavailable.')
    if not download_path.exists():
        raise RuntimeError(f'Downloaded update was not found: {download_path}')
    _assert_directory_writable(target_path.parent)

    update_root = updates_dir()
    script_path = update_root / 'apply_budget_terminal_update.ps1'
    script_path.write_text(_updater_script_text(), encoding='utf-8')
    timestamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_path = target_path.with_name(f'{target_path.name}.backup')
    log_path = update_root / f'update-{normalize_version(latest_version) or "unknown"}-{timestamp}.log'
    powershell_path = shutil.which('powershell.exe') or shutil.which('powershell') or 'powershell.exe'
    command = [
        powershell_path,
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-WindowStyle',
        'Hidden',
        '-File',
        str(script_path),
        '-ProcessId',
        str(os.getpid()),
        '-TargetPath',
        str(target_path),
        '-DownloadPath',
        str(download_path),
        '-BackupPath',
        str(backup_path),
        '-LogPath',
        str(log_path),
        '-WaitTimeoutSeconds',
        str(UPDATE_WAIT_TIMEOUT_SECONDS),
    ]
    creationflags = 0
    if os.name == 'nt':
        creationflags = (
            getattr(subprocess, 'DETACHED_PROCESS', 0)
            | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            | getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        )
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )
    logger.info('Launched Budget Terminal updater for v%s from %s.', latest_version, release_url or RELEASES_URL)
    return {
        'ok': True,
        'script_path': str(script_path),
        'log_path': str(log_path),
        'target_path': str(target_path),
        'backup_path': str(backup_path),
    }


class UpdateCheckWorker(QObject):
    """Check GitHub Releases for packaged updates without blocking the Settings UI."""

    status = Signal(str)
    finished = Signal(object)

    def __init__(self, current_version: str) -> None:
        super().__init__()
        self.current_version = normalize_version(current_version)

    def run(self) -> None:
        self.status.emit('Checking GitHub Releases for updates...')
        self.finished.emit(check_for_update(self.current_version))


class UpdateDownloadWorker(QObject):
    """Download and verify a packaged update without blocking the Settings UI."""

    status = Signal(str)
    finished = Signal(object)

    def __init__(self, asset: dict[str, Any], target_dir: str | Path) -> None:
        super().__init__()
        self.asset = dict(asset or {})
        self.target_dir = Path(target_dir)

    def run(self) -> None:
        try:
            self.status.emit('Downloading update...')
            result = download_update(
                _asset_download_url(self.asset),
                self.asset.get('digest'),
                self.target_dir,
                expected_size=self.asset.get('size'),
                asset_name=self.asset.get('name'),
                progress_callback=self.status.emit,
            )
            self.finished.emit(result)
        except Exception as exc:
            logger.exception('Budget Terminal update download failed.')
            self.finished.emit({
                'ok': False,
                'message': f'Update download failed: {exc}',
            })
