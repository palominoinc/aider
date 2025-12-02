"""MCP service for managing MCP server connections and tool execution."""

import json
from typing import Any, Dict, List, Optional, Tuple

from .mcp_client import MCPClient, MCPClientError, MCPConnectionError, MCPToolError
from .mcp_config import MCPConfig, MCPServerConfig


class MCPService:
    """Manages MCP server connections and provides tool integration for aider."""

    def __init__(self, io, config_file: Optional[str] = None,
                 cli_servers: Optional[List[str]] = None, verbose: bool = False):
        """Initialize MCP service.

        Args:
            io: Aider's I/O interface for user feedback
            config_file: Path to YAML configuration file
            cli_servers: List of server configs from CLI
            verbose: Enable verbose output
        """
        self.io = io
        self.verbose = verbose
        self.clients: Dict[str, MCPClient] = {}
        self.tools: Dict[str, Tuple[str, Dict[str, Any]]] = {}  # tool_name -> (server_name, schema)

        # Load configuration
        try:
            self.config = MCPConfig(config_file=config_file, cli_servers=cli_servers)
        except Exception as e:
            raise ValueError(f"Failed to load MCP configuration: {e}")

    def start_servers(self):
        """Connect to all configured MCP servers."""
        if not self.config.servers:
            if self.verbose:
                self.io.tool_output("No MCP servers configured")
            return

        for server_name, server_config in self.config.servers.items():
            try:
                if self.verbose:
                    self.io.tool_output(f"Connecting to MCP server: {server_name}")

                client = MCPClient(
                    server_name=server_name,
                    command=server_config.command,
                    args=server_config.args,
                    env=server_config.get_env()
                )

                client.connect(timeout=10.0)
                self.clients[server_name] = client

                if self.verbose:
                    self.io.tool_output(f"  Connected to {server_name}")

            except MCPConnectionError as e:
                self.io.tool_error(f"Failed to connect to '{server_name}': {e}")
            except Exception as e:
                self.io.tool_error(f"Unexpected error connecting to '{server_name}': {e}")

    def discover_tools(self):
        """Discover tools from all connected servers."""
        if not self.clients:
            if self.verbose:
                self.io.tool_output("No MCP servers connected")
            return

        for server_name, client in self.clients.items():
            try:
                if self.verbose:
                    self.io.tool_output(f"Discovering tools from: {server_name}")

                tools = client.list_tools(timeout=5.0)

                for tool in tools:
                    tool_name = tool["name"]
                    # Store with server context
                    self.tools[f"{server_name}_{tool_name}"] = (server_name, tool)

                if self.verbose:
                    self.io.tool_output(f"  Found {len(tools)} tool(s) from {server_name}")

            except MCPClientError as e:
                self.io.tool_error(f"Failed to discover tools from '{server_name}': {e}")
            except Exception as e:
                self.io.tool_error(f"Unexpected error discovering tools from '{server_name}': {e}")

    def _fix_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Fix common schema issues for OpenAI compatibility.

        Args:
            schema: JSON schema to fix

        Returns:
            Fixed schema
        """
        if not isinstance(schema, dict):
            return schema

        # Make a copy to avoid modifying original
        fixed = dict(schema)

        # Fix arrays missing items field
        if fixed.get("type") == "array" and "items" not in fixed:
            fixed["items"] = {"type": "string"}  # Default to string array

        # Recursively fix nested schemas
        if "properties" in fixed:
            fixed["properties"] = {
                k: self._fix_schema(v) for k, v in fixed["properties"].items()
            }

        if "items" in fixed:
            fixed["items"] = self._fix_schema(fixed["items"])

        if "additionalProperties" in fixed and isinstance(fixed["additionalProperties"], dict):
            fixed["additionalProperties"] = self._fix_schema(fixed["additionalProperties"])

        return fixed

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Convert MCP tool schemas to OpenAI function call format.

        Returns list of tool schemas suitable for passing to LLM.
        """
        schemas = []

        # TEMPORARY DEBUG: Only return first 20 tools to test
        tool_items = list(self.tools.items())[:20]

        for namespaced_tool_name, (server_name, mcp_schema) in tool_items:
            # Convert to OpenAI function schema format
            openai_schema = {
                "name": f"mcp_{namespaced_tool_name}",
                "description": mcp_schema.get("description", ""),
            }

            # Add parameters from inputSchema
            input_schema = mcp_schema.get("inputSchema", {})
            if input_schema:
                # Fix schema issues before adding
                openai_schema["parameters"] = self._fix_schema(input_schema)
            else:
                # Default to empty object schema if no input schema
                openai_schema["parameters"] = {
                    "type": "object",
                    "properties": {}
                }

            schemas.append(openai_schema)

        return schemas

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Execute an MCP tool.

        Args:
            tool_name: Full namespaced tool name (e.g., "mcp_filesystem_read_file")
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        # Remove "mcp_" prefix if present
        if tool_name.startswith("mcp_"):
            tool_name = tool_name[4:]

        # Find the tool
        if tool_name not in self.tools:
            raise MCPToolError(f"Tool not found: {tool_name}")

        server_name, tool_schema = self.tools[tool_name]

        # Extract the actual tool name (without server prefix)
        actual_tool_name = tool_name
        if tool_name.startswith(f"{server_name}_"):
            actual_tool_name = tool_name[len(server_name) + 1:]

        # Get the client
        client = self.clients.get(server_name)
        if not client:
            raise MCPToolError(f"Server not connected: {server_name}")

        if not client.is_connected():
            raise MCPToolError(f"Server disconnected: {server_name}")

        # Execute the tool
        try:
            result = client.call_tool(actual_tool_name, arguments, timeout=30.0)
            return result
        except MCPToolError:
            raise
        except Exception as e:
            raise MCPToolError(f"Tool execution failed: {e}")

    def get_connected_servers(self) -> List[str]:
        """Get list of connected server names."""
        return [name for name, client in self.clients.items() if client.is_connected()]

    def get_available_tools(self) -> Dict[str, str]:
        """Get mapping of tool names to server names."""
        return {tool_name: server_name for tool_name, (server_name, _) in self.tools.items()}

    def shutdown(self):
        """Gracefully disconnect from all MCP servers."""
        if self.verbose:
            self.io.tool_output("Shutting down MCP service")

        for server_name, client in self.clients.items():
            try:
                if self.verbose:
                    self.io.tool_output(f"  Disconnecting from {server_name}")
                client.disconnect(timeout=5.0)
            except Exception as e:
                if self.verbose:
                    self.io.tool_error(f"Error disconnecting from '{server_name}': {e}")

        self.clients.clear()
        self.tools.clear()

    def __repr__(self):
        connected = len([c for c in self.clients.values() if c.is_connected()])
        return f"MCPService(servers={connected}/{len(self.clients)}, tools={len(self.tools)})"
