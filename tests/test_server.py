"""Smoke tests for the server entry point — build_server returns a FastMCP."""

from mcp.server.fastmcp import FastMCP

from nfl.server import build_server


def test_build_server_returns_fastmcp_instance() -> None:
    server = build_server()
    assert isinstance(server, FastMCP)


def test_build_server_accepts_overrides() -> None:
    server = build_server(host="127.0.0.1", port=9999, api_host="https://example.invalid")
    assert isinstance(server, FastMCP)
