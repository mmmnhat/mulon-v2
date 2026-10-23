"""MCP server mini cho test Phase 3: chạy qua stdio bằng SDK thật.

Chạy: python tests/mcp_echo_server.py  (giao thức MCP trên stdio)
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("echo")


@mcp.tool()
def echo(text: str) -> str:
    """Trả lại nguyên văn chuỗi được đưa vào."""
    return f"echo:{text}"


@mcp.tool()
def add(a: int, b: int) -> int:
    """Cộng hai số nguyên."""
    return a + b


if __name__ == "__main__":
    mcp.run()
