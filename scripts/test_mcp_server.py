"""Focused protocol and Windows stdio smoke tests for Budget Terminal MCP."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.mcp.protocol import McpProtocol
from budget_terminal_app.mcp.server import read_messages


class _StatusBridge:
    def __init__(self) -> None:
        self.news_call = None

    def status(self) -> dict[str, Any]:
        return {'application': 'Budget Terminal MCP', 'current_page': 'Dashboard'}

    def portfolio_news(self, portfolio, *, max_articles, max_per_ticker):
        self.news_call = (portfolio, max_articles, max_per_ticker)
        return {
            'portfolio': portfolio,
            'queried_tickers': ['AAA'],
            'articles': [{'ticker': 'AAA', 'title': 'AAA news'}],
            'count': 1,
            'failed_tickers': [],
        }


def _request(request_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {'jsonrpc': '2.0', 'id': request_id, 'method': method}
    if params is not None:
        message['params'] = params
    return message


def test_protocol_basics() -> None:
    bridge = _StatusBridge()
    protocol = McpProtocol(bridge)
    initialized = protocol.handle(
        _request(
            1,
            'initialize',
            {
                'protocolVersion': McpProtocol.PROTOCOL_VERSION,
                'capabilities': {},
                'clientInfo': {'name': 'smoke-test', 'version': '1.0'},
            },
        )
    )
    assert initialized is not None
    assert initialized['result']['protocolVersion'] == McpProtocol.PROTOCOL_VERSION
    assert protocol.handle(_request(2, 'ping')) == {'jsonrpc': '2.0', 'id': 2, 'result': {}}
    tools = protocol.handle(_request(3, 'tools/list'))
    assert tools is not None
    tool_names = {item['name'] for item in tools['result']['tools']}
    assert {'app_status', 'list_pages', 'get_portfolio_news', 'inspect_page', 'interact', 'capture_page'} <= tool_names
    news = protocol.handle(
        _request(
            4,
            'tools/call',
            {'name': 'get_portfolio_news', 'arguments': {'portfolio': 'Growth', 'max_articles': 12, 'max_per_ticker': 2}},
        )
    )
    assert news is not None
    assert news['result']['structuredContent']['count'] == 1
    assert bridge.news_call == ('Growth', 12, 2)
    assert protocol.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) is None


def test_message_framing() -> None:
    first = json.dumps(_request(1, 'ping')).encode('utf-8')
    second = json.dumps(_request(2, 'tools/list')).encode('utf-8')
    stream = io.BytesIO(
        b'not-json\n'
        + first
        + b'\n'
        + f'Content-Length: {len(second)}\r\n\r\n'.encode('ascii')
        + second
    )
    messages = list(read_messages(stream))
    assert [message['id'] for message in messages] == [1, 2]


def test_headless_subprocess() -> None:
    requests = [
        _request(
            1,
            'initialize',
            {
                'protocolVersion': McpProtocol.PROTOCOL_VERSION,
                'capabilities': {},
                'clientInfo': {'name': 'windows-subprocess-smoke', 'version': '1.0'},
            },
        ),
        _request(2, 'ping'),
        _request(3, 'tools/list'),
        _request(4, 'tools/call', {'name': 'app_status', 'arguments': {}}),
    ]
    stdin_payload = b'not-json\n' + b''.join(
        json.dumps(message, separators=(',', ':')).encode('utf-8') + b'\n'
        for message in requests
    )

    with tempfile.TemporaryDirectory(prefix='budget-terminal-mcp-') as temp_dir:
        temp_root = Path(temp_dir)
        env = dict(os.environ)
        env.update(
            {
                'APPDATA': str(temp_root / 'AppData' / 'Roaming'),
                'LOCALAPPDATA': str(temp_root / 'AppData' / 'Local'),
                'USERPROFILE': str(temp_root),
                'QT_QPA_PLATFORM': 'offscreen',
                'BUDGET_TERMINAL_SKIP_LOCAL_VENV': '1',
            }
        )
        process = subprocess.Popen(
            [sys.executable, str(PROJECT_ROOT / 'budget_terminal_mcp.py'), '--headless'],
            cwd=PROJECT_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = process.communicate(input=stdin_payload, timeout=120)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            raise AssertionError(f'MCP subprocess did not stop after stdin EOF. stderr={stderr.decode(errors="replace")}')

    assert process.returncode == 0, stderr.decode('utf-8', errors='replace')
    response_lines = [line for line in stdout.decode('utf-8').splitlines() if line.strip()]
    assert len(response_lines) == len(requests), f'Unexpected MCP stdout: {stdout!r}'
    responses = [json.loads(line) for line in response_lines]
    assert [response['id'] for response in responses] == [1, 2, 3, 4]
    assert responses[0]['result']['serverInfo']['name'] == 'budget-terminal'
    assert responses[1]['result'] == {}
    assert responses[2]['result']['tools']
    status_content = json.loads(responses[3]['result']['content'][0]['text'])
    assert status_content['current_page']


def test_visible_lifecycle() -> None:
    with tempfile.TemporaryDirectory(prefix='budget-terminal-mcp-visible-') as temp_dir:
        temp_root = Path(temp_dir)
        env = dict(os.environ)
        env.update(
            {
                'APPDATA': str(temp_root / 'AppData' / 'Roaming'),
                'LOCALAPPDATA': str(temp_root / 'AppData' / 'Local'),
                'USERPROFILE': str(temp_root),
                'QT_QPA_PLATFORM': 'offscreen',
                'BUDGET_TERMINAL_SKIP_LOCAL_VENV': '1',
            }
        )
        process = subprocess.Popen(
            [sys.executable, str(PROJECT_ROOT / 'budget_terminal_mcp.py')],
            cwd=PROJECT_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        try:
            for message in (
                _request(1, 'initialize', {'protocolVersion': McpProtocol.PROTOCOL_VERSION, 'capabilities': {}, 'clientInfo': {'name': 'visible-lifecycle', 'version': '1.0'}}),
                _request(2, 'tools/call', {'name': 'app_status', 'arguments': {}}),
            ):
                process.stdin.write(json.dumps(message).encode('utf-8') + b'\n')
            process.stdin.flush()
            responses = [json.loads(process.stdout.readline().decode('utf-8')) for _ in range(2)]
            assert process.poll() is None, 'visible MCP process should remain alive while stdin stays connected'
            status = json.loads(responses[1]['result']['content'][0]['text'])
            assert status['window_visible'] is True
            assert isinstance(status['process_id'], int) and status['process_id'] > 0
            process.stdin.close()
            process.wait(timeout=30)
        except Exception:
            process.kill()
            process.wait(timeout=10)
            raise
        assert process.returncode == 0, process.stderr.read().decode('utf-8', errors='replace')


def main() -> int:
    test_protocol_basics()
    print('PASS protocol basics')
    test_message_framing()
    print('PASS JSON-lines, malformed input, and Content-Length framing')
    test_headless_subprocess()
    print('PASS Windows headless subprocess handshake and EOF shutdown')
    test_visible_lifecycle()
    print('PASS visible window remains alive until MCP stdin closes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
