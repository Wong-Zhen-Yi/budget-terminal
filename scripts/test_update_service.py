from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app import update_service


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.closed = False

    def raise_for_status(self) -> None:
        pass

    def iter_content(self, chunk_size: int):
        step = max(1, int(chunk_size or 1))
        for index in range(0, len(self.content), step):
            yield self.content[index:index + step]

    def close(self) -> None:
        self.closed = True


class _FakeRequests:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({'url': url, **kwargs})
        return _FakeResponse(self.content)


def test_version_helpers() -> None:
    _assert(update_service.normalize_version('v0.908') == '0.908', 'leading v should be removed')
    _assert(update_service.normalize_version('refs/tags/v1.2.3') == '1.2.3', 'tag refs should normalize')
    _assert(update_service.is_newer_version('v0.909', '0.908'), 'v0.909 should be newer than v0.908')
    _assert(not update_service.is_newer_version('v0.908', '0.908'), 'same version should not be newer')
    _assert(update_service.is_newer_version('v1.0', 'v0.999'), 'major version should sort newer')


def test_release_payload_parsing() -> None:
    digest = 'sha256:' + ('a' * 64)
    payload = {
        'tag_name': 'v0.909',
        'draft': False,
        'prerelease': False,
        'html_url': 'https://example.test/releases/v0.909',
        'assets': [
            {
                'name': 'BudgetTerminal-v0.909-windows.zip',
                'browser_download_url': 'https://example.test/BudgetTerminal-v0.909-windows.zip',
                'size': 10,
                'digest': digest,
            },
            {
                'name': 'BudgetTerminal-v0.909.exe',
                'browser_download_url': 'https://example.test/BudgetTerminal-v0.909.exe',
                'size': 11,
                'digest': digest,
            },
        ],
    }
    result = update_service.build_update_check_result('0.908', payload)
    _assert(result['ok'], 'newer stable release should parse successfully')
    _assert(result['update_available'], 'newer release should be marked available')
    _assert(result['asset']['name'] == 'BudgetTerminal-v0.909.exe', 'the one-file EXE asset should be selected')

    current_result = update_service.build_update_check_result('0.909', payload)
    _assert(current_result['ok'], 'current release should parse successfully')
    _assert(not current_result['update_available'], 'same release should not be marked available')
    _assert(current_result['asset'] is None, 'no asset is needed when already current')

    missing_asset = dict(payload)
    missing_asset['assets'] = [payload['assets'][0]]
    missing_result = update_service.build_update_check_result('0.908', missing_asset)
    _assert(not missing_result['ok'], 'newer release without an EXE should be blocked')
    _assert(missing_result['update_available'], 'missing asset result should still identify available version')


def test_download_verification() -> None:
    content = b'Budget Terminal test executable bytes'
    digest = 'sha256:' + hashlib.sha256(content).hexdigest()
    fake_requests = _FakeRequests(content)
    original_requests = update_service.requests
    update_service.requests = fake_requests
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = update_service.download_update(
                'https://example.test/BudgetTerminal-v0.909.exe',
                digest,
                tmp,
                expected_size=len(content),
                asset_name='BudgetTerminal-v0.909.exe',
            )
            output_path = Path(result['path'])
            _assert(output_path.exists(), 'verified update should be written to disk')
            _assert(output_path.read_bytes() == content, 'downloaded update bytes should match response')
            _assert(result['digest_verified'], 'sha256 digest should be marked verified')
            _assert(fake_requests.calls[-1]['stream'] is True, 'download should stream response content')

        with tempfile.TemporaryDirectory() as tmp:
            try:
                update_service.download_update(
                    'https://example.test/BudgetTerminal-v0.909.exe',
                    'sha256:' + ('0' * 64),
                    tmp,
                    expected_size=len(content),
                    asset_name='BudgetTerminal-v0.909.exe',
                )
            except RuntimeError as exc:
                _assert('SHA256' in str(exc), 'bad digest should raise a SHA256 error')
            else:
                raise AssertionError('bad digest should fail verification')
    finally:
        update_service.requests = original_requests


def test_source_launch_is_not_packaged_update_supported() -> None:
    original_is_frozen = update_service.is_frozen
    update_service.is_frozen = lambda: False
    try:
        status = update_service.packaged_update_status()
    finally:
        update_service.is_frozen = original_is_frozen
    _assert(not status['supported'], 'source launches should not support packaged self-update install')
    _assert('packaged Windows builds' in status['message'] or os.name != 'nt', 'unsupported status should explain packaged builds')


def main() -> None:
    test_version_helpers()
    test_release_payload_parsing()
    test_download_verification()
    test_source_launch_is_not_packaged_update_supported()
    print('update service tests passed')


if __name__ == '__main__':
    main()
