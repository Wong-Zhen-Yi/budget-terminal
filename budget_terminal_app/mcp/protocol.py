from __future__ import annotations

from typing import Any, Optional

from .bridge import BridgeError, BudgetTerminalBridge


class McpProtocol:
    """Small MCP 2024-11-05 implementation with no extra runtime dependency."""

    PROTOCOL_VERSION = "2024-11-05"

    def __init__(self, bridge: BudgetTerminalBridge) -> None:
        self.bridge = bridge

    def handle(self, message: dict[str, Any]) -> Optional[dict[str, Any]]:
        request_id = message.get("id")
        method = str(message.get("method") or "")
        if request_id is None:
            return None
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": self.PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}, "resources": {"subscribe": False, "listChanged": False}},
                    "serverInfo": {"name": "budget-terminal", "version": "1.0.0"},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.tool_definitions()}
            elif method == "tools/call":
                result = self.call_tool(message.get("params") or {})
            elif method == "resources/list":
                result = {"resources": self.resource_definitions()}
            elif method == "resources/read":
                result = self.read_resource(message.get("params") or {})
            elif method in {"prompts/list", "completion/complete"}:
                result = {"prompts": []} if method == "prompts/list" else {"completion": {"values": [], "total": 0, "hasMore": False}}
            else:
                return self._error(request_id, -32601, f"Method not found: {method}")
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except (BridgeError, TypeError, ValueError) as exc:
            return self._error(request_id, -32602, str(exc))
        except Exception as exc:
            return self._error(request_id, -32603, f"Budget Terminal MCP error: {exc}")

    def call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = str(params.get("name") or "")
        args = params.get("arguments") or {}
        if name == "app_status":
            value = self.bridge.status()
        elif name == "list_pages":
            value = self.bridge.list_pages()
        elif name == "get_portfolio_tickers":
            value = self.bridge.portfolio_tickers(args.get("portfolio", "active"))
        elif name == "get_portfolio_news":
            value = self.bridge.portfolio_news(
                args.get("portfolio", "active"),
                max_articles=args.get("max_articles", 50),
                max_per_ticker=args.get("max_per_ticker", 3),
            )
        elif name == "navigate_page":
            value = self.bridge.navigate(args.get("page"))
        elif name == "inspect_page":
            value = self.bridge.inspect_page(max_rows=args.get("max_rows", 100), max_columns=args.get("max_columns", 30))
        elif name == "export_page_for_llm":
            text = self.bridge.export_page(format=args.get("format", "markdown"), max_rows=args.get("max_rows", 100), max_columns=args.get("max_columns", 30))
            return {"content": [{"type": "text", "text": text}]}
        elif name == "interact":
            value = self.bridge.interact(args.get("control_id", ""), args.get("action", ""), args.get("value"), args.get("row"), args.get("column"))
        elif name == "refresh_page":
            value = self.bridge.refresh()
        elif name == "wait_for_ui":
            value = self.bridge.wait_for_ui(args.get("timeout_ms", 1000), args.get("settle_ms", 100))
        elif name == "set_privacy_mode":
            value = self.bridge.set_privacy_mode(bool(args.get("obscured", True)))
        elif name == "capture_page":
            return {"content": [{"type": "image", "data": self.bridge.capture_page(), "mimeType": "image/png"}]}
        else:
            raise BridgeError(f"Unknown tool: {name}")
        import json
        return {"content": [{"type": "text", "text": json.dumps(value, indent=2, ensure_ascii=False)}], "structuredContent": value}

    def resource_definitions(self) -> list[dict[str, Any]]:
        return [
            {"uri": "budget-terminal://status", "name": "Application status", "mimeType": "application/json"},
            {"uri": "budget-terminal://pages", "name": "Page registry", "mimeType": "application/json"},
            {"uri": "budget-terminal://current-page", "name": "Current page data", "mimeType": "application/json"},
        ]

    def read_resource(self, params: dict[str, Any]) -> dict[str, Any]:
        import json
        uri = str(params.get("uri") or "")
        if uri == "budget-terminal://status":
            value = self.bridge.status()
        elif uri == "budget-terminal://pages":
            value = self.bridge.list_pages()
        elif uri == "budget-terminal://current-page":
            value = self.bridge.inspect_page()
        else:
            raise BridgeError(f"Unknown resource: {uri}")
        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(value, indent=2, ensure_ascii=False)}]}

    @classmethod
    def tool_definitions(cls) -> list[dict[str, Any]]:
        integer_limit = {"type": "integer", "minimum": 1}
        return [
            cls._tool("app_status", "Get the controlled app's current page, privacy, and refresh state."),
            cls._tool("list_pages", "List every real navigable page and its initialization state."),
            cls._tool(
                "get_portfolio_tickers",
                "Read saved ticker symbols directly from the active, main, named, or all portfolios.",
                {"portfolio": {"description": "active, main, all, a portfolio ID, or an exact portfolio name", "type": "string"}},
            ),
            cls._tool(
                "get_portfolio_news",
                "Fetch current ticker-specific headlines for the active, main, named, or all portfolios.",
                {
                    "portfolio": {"description": "active, main, all, a portfolio ID, or an exact portfolio name", "type": "string"},
                    "max_articles": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
                    "max_per_ticker": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
                },
            ),
            cls._tool("navigate_page", "Navigate to a page by exact name or numeric index.", {"page": {"description": "Page name or index", "anyOf": [{"type": "string"}, {"type": "integer"}]}}, ["page"]),
            cls._tool("inspect_page", "Read visible text, controls, tables, lists, and text blocks from the current page.", {"max_rows": integer_limit, "max_columns": integer_limit}),
            cls._tool("export_page_for_llm", "Export current visible page data as compact Markdown or JSON for analysis and summarization.", {"format": {"type": "string", "enum": ["markdown", "json"]}, "max_rows": integer_limit, "max_columns": integer_limit}),
            cls._tool("interact", "Operate a control returned by inspect_page: click, set_text, select, set_value, check, or activate_cell.", {"control_id": {"type": "string"}, "action": {"type": "string", "enum": ["click", "set_text", "select", "set_value", "check", "activate_cell"]}, "value": {}, "row": {"type": "integer"}, "column": {"type": "integer"}}, ["control_id", "action"]),
            cls._tool("refresh_page", "Request the same refresh action as the app's Reload button."),
            cls._tool("wait_for_ui", "Process UI and worker events until refresh settles or timeout expires.", {"timeout_ms": {"type": "integer", "minimum": 0, "maximum": 30000}, "settle_ms": {"type": "integer", "minimum": 0}}),
            cls._tool("set_privacy_mode", "Obscure or reveal pages configured as sensitive in app settings.", {"obscured": {"type": "boolean"}}, ["obscured"]),
            cls._tool("capture_page", "Capture the current page as a PNG image for visual inspection."),
        ]

    @staticmethod
    def _tool(
        name: str,
        description: str,
        properties: Optional[dict[str, Any]] = None,
        required: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        return {"name": name, "description": description, "inputSchema": {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
