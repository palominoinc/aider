"""Synchronous wrapper for async MCP SDK client."""

import asyncio
import json
import threading
from concurrent.futures import Future
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClientError(Exception):
    """Base exception for MCP client errors."""
    pass


class MCPConnectionError(MCPClientError):
    """Server connection failed."""
    pass


class MCPToolError(MCPClientError):
    """Tool execution failed."""
    pass


class MCPClient:
    """Synchronous wrapper around MCP SDK's async client.

    Runs an event loop in a background thread and provides sync methods
    for interacting with an MCP server via stdio.
    """

    def __init__(self, server_name: str, command: str, args: Optional[List[str]] = None,
                 env: Optional[Dict[str, str]] = None):
        self.server_name = server_name
        self.command = command
        self.args = args or []
        self.env = env or {}

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._session: Optional[ClientSession] = None
        self._stdio_context = None
        self._read = None
        self._write = None
        self._connected = False
        self._tools_cache: Optional[List[Dict[str, Any]]] = None

    def connect(self, timeout: float = 10.0):
        """Start background thread with event loop and connect to server."""
        if self._connected:
            return

        # Start event loop thread
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()

        # Connect to server
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._async_connect(),
                self._loop
            )
            future.result(timeout=timeout)
            self._connected = True
        except Exception as e:
            self._cleanup()
            import traceback
            error_details = f"{type(e).__name__}: {str(e)}"
            if not str(e):
                error_details = f"{type(e).__name__} (no message)"
            raise MCPConnectionError(
                f"Failed to connect to MCP server '{self.server_name}': {error_details}\n"
                f"Traceback: {traceback.format_exc()}"
            )

    def _run_event_loop(self):
        """Run the event loop in the background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _async_connect(self):
        """Async method to connect to the MCP server."""
        # Debug output for credentials
        if self.env:
            print(f"\n[DEBUG mcp_client.py] Starting MCP server '{self.server_name}' with env vars:")
            for key, value in self.env.items():
                # Mask password values
                if 'password' in key.lower() or 'pass' in key.lower():
                    display_value = '*' * len(value) if value else '<empty>'
                else:
                    display_value = value if value else '<empty>'
                print(f"  {key}: {display_value}")

        server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env if self.env else None
        )

        # Create stdio client context - keep reference to prevent garbage collection
        self._stdio_context = stdio_client(server_params)
        self._read, self._write = await self._stdio_context.__aenter__()

        # Create session
        self._session = ClientSession(self._read, self._write)
        await self._session.__aenter__()

        # Initialize session
        await self._session.initialize()

    def list_tools(self, timeout: float = 5.0) -> List[Dict[str, Any]]:
        """List all available tools from the server.

        Returns list of tool schemas in MCP format.
        """
        if not self._connected:
            raise MCPClientError("Client not connected. Call connect() first.")

        if self._tools_cache is not None:
            return self._tools_cache

        try:
            future = asyncio.run_coroutine_threadsafe(
                self._async_list_tools(),
                self._loop
            )
            tools = future.result(timeout=timeout)
            self._tools_cache = tools
            return tools
        except Exception as e:
            raise MCPClientError(f"Failed to list tools from '{self.server_name}': {e}")

    async def _async_list_tools(self) -> List[Dict[str, Any]]:
        """Async method to list tools."""
        response = await self._session.list_tools()

        tools = []
        for tool in response.tools:
            tool_dict = {
                "name": tool.name,
                "description": tool.description or "",
            }

            # Add input schema if available
            if hasattr(tool, "inputSchema"):
                tool_dict["inputSchema"] = tool.inputSchema

            tools.append(tool_dict)

        return tools

    def call_tool(self, tool_name: str, arguments: Dict[str, Any], timeout: float = 30.0) -> Any:
        """Call a tool and return its result.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments as a dictionary
            timeout: Maximum time to wait for result

        Returns:
            Tool result (typically a dict or list)
        """
        if not self._connected:
            raise MCPClientError("Client not connected. Call connect() first.")

        try:
            future = asyncio.run_coroutine_threadsafe(
                self._async_call_tool(tool_name, arguments),
                self._loop
            )
            return future.result(timeout=timeout)
        except asyncio.TimeoutError:
            raise MCPToolError(f"Tool '{tool_name}' timed out after {timeout}s")
        except Exception as e:
            raise MCPToolError(f"Tool '{tool_name}' failed: {e}")

    async def _async_call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Async method to call a tool."""
        result = await self._session.call_tool(tool_name, arguments)

        # Extract content from result
        if hasattr(result, "content"):
            content = result.content

            # Handle list of content items
            if isinstance(content, list) and len(content) > 0:
                first_item = content[0]

                # Extract text from TextContent
                if hasattr(first_item, "text"):
                    return first_item.text

                # Handle other content types
                if hasattr(first_item, "data"):
                    return first_item.data

            return content

        return result

    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected

    def disconnect(self, timeout: float = 5.0):
        """Gracefully disconnect from server and clean up."""
        if not self._connected:
            return

        try:
            if self._loop and self._session:
                future = asyncio.run_coroutine_threadsafe(
                    self._async_disconnect(),
                    self._loop
                )
                future.result(timeout=timeout)
        except Exception:
            pass  # Best effort cleanup
        finally:
            self._cleanup()

    async def _async_disconnect(self):
        """Async method to disconnect."""
        if self._session:
            await self._session.__aexit__(None, None, None)
            self._session = None

        if self._stdio_context:
            await self._stdio_context.__aexit__(None, None, None)
            self._stdio_context = None

    def _cleanup(self):
        """Clean up resources."""
        self._connected = False

        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        self._loop = None
        self._thread = None
        self._session = None
        self._tools_cache = None

    def __repr__(self):
        status = "connected" if self._connected else "disconnected"
        return f"MCPClient(server={self.server_name!r}, status={status})"
