"""Thin client for the MCP knowledge-base server.

The MCP server at `http://localhost:3800/mcp` (a.k.a. ``understory``)
implements the Model Context Protocol over Streamable HTTP using
JSON-RPC 2.0. It exposes knowledge-base tools — ``memory_query``,
``memory_add``, ``memory_update``, ``memory_status``, ``memory_maintain``.

This module currently exposes only :func:`memory_query`, which is the
tool we use to ask natural-language questions about stored knowledge
(supplier delivery details, contacts, lead times, MOQs, etc.).

The server is stateless across requests — a fresh ``initialize``
handshake on every call is enough; no ``mcp-session-id`` is required.
"""

import json
import urllib.error
import urllib.request

# Default endpoint — overridable per call. Centralised here so other
# modules can reuse the same constant.
DEFAULT_MCP_URL = "http://localhost:3800/mcp"
MCP_PROTOCOL_VERSION = "2025-03-26"
DEFAULT_TIMEOUT_SECONDS = 20.0


class MCPClientError(RuntimeError):
    """Raised when the MCP server returns an error or the transport fails."""


def _post(payload, url, timeout):
    """POST a JSON-RPC payload and return the parsed SSE ``data:`` line."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode()
    except urllib.error.HTTPError as exc:
        # Server returned a non-2xx status. Body may carry a JSON-RPC error.
        body = exc.read().decode(errors="replace")
        raise MCPClientError(
            f"MCP HTTP {exc.code} {exc.reason}: {body[:300]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise MCPClientError(f"MCP connection error: {exc.reason}") from exc

    # The server responds with text/event-stream for ``tools/call`` and
    # with a plain JSON body for ``initialize``. Handle both: accept the
    # last ``data:`` SSE frame if present, otherwise parse the body as
    # JSON directly.
    last_data = None
    for line in body.splitlines():
        if line.startswith("data:"):
            last_data = line[len("data:"):].strip()
    payload = last_data if last_data is not None else body
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise MCPClientError(f"MCP returned non-JSON payload: {exc}") from exc


def _initialize(url, timeout):
    """Send the JSON-RPC ``initialize`` handshake (stateless)."""
    return _post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "streamlit-history", "version": "0.1"},
            },
        },
        url,
        timeout,
    )


def memory_query(
    question: str,
    *,
    url: str = DEFAULT_MCP_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Ask the MCP knowledge base a natural-language question.

    Returns the markdown-formatted answer produced by the server. If
    the server reports a JSON-RPC error, raises :class:`MCPClientError`.
    """
    if not question or not question.strip():
        raise MCPClientError("memory_query: question must be a non-empty string")

    # Stateless handshake — no session id is reused or required.
    _initialize(url, timeout)

    response = _post(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "memory_query",
                "arguments": {"question": question},
            },
        },
        url,
        timeout,
    )

    if "error" in response:
        raise MCPClientError(f"MCP error: {response['error']}")

    result = response.get("result") or {}
    content = result.get("content") or []
    if not content:
        raise MCPClientError(f"MCP returned empty content: {response}")

    # The server returns content items; we only need the first text item.
    for item in content:
        if item.get("type") == "text" and item.get("text"):
            return item["text"]

    raise MCPClientError(f"MCP returned no text content: {response}")