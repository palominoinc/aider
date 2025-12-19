"""Configuration loading for MCP servers."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class MCPServerConfig:
    """Configuration for a single MCP server."""

    def __init__(self, name: str, command: str, args: Optional[List[str]] = None,
                 env: Optional[Dict[str, str]] = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}

    def get_env(self) -> Dict[str, str]:
        """Get environment variables with ${VAR} expansion."""
        expanded_env = {}
        for key, value in self.env.items():
            if value.startswith("${") and value.endswith("}"):
                env_var = value[2:-1]
                expanded_env[key] = os.environ.get(env_var, "")
            else:
                expanded_env[key] = value
        return expanded_env

    def __repr__(self):
        return f"MCPServerConfig(name={self.name!r}, command={self.command!r})"


class MCPConfig:
    """Loads and manages MCP server configurations."""

    def __init__(self, config_file: Optional[str] = None, cli_servers: Optional[List[str]] = None):
        self.servers: Dict[str, MCPServerConfig] = {}

        if config_file:
            self._load_from_file(config_file)

        if cli_servers:
            self._load_from_cli(cli_servers)

    def _load_from_file(self, config_file: str):
        """Load server configurations from YAML file."""
        path = Path(config_file).expanduser()

        if not path.exists():
            raise FileNotFoundError(f"MCP config file not found: {config_file}")

        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in MCP config file: {e}")

        if not isinstance(data, dict) or "servers" not in data:
            raise ValueError("MCP config file must contain 'servers' key")

        servers = data["servers"]
        if not isinstance(servers, dict):
            raise ValueError("'servers' must be a dictionary")

        for name, config in servers.items():
            if not isinstance(config, dict):
                raise ValueError(f"Server config for '{name}' must be a dictionary")

            command = config.get("command")
            if not command:
                raise ValueError(f"Server '{name}' missing required 'command' field")

            args = config.get("args", [])
            env = config.get("env", {})

            # Expand ${VAR} in args
            expanded_args = []
            for arg in args:
                if isinstance(arg, str) and arg.startswith("${") and arg.endswith("}"):
                    env_var = arg[2:-1]
                    expanded_args.append(os.environ.get(env_var, arg))
                else:
                    expanded_args.append(str(arg))

            self.servers[name] = MCPServerConfig(name, command, expanded_args, env)

    def _load_from_cli(self, cli_servers: List[str]):
        """Load server configurations from CLI arguments.

        Format: name=command [args...]
        Example: filesystem=npx -y @modelcontextprotocol/server-filesystem /tmp
        """
        for server_str in cli_servers:
            if "=" not in server_str:
                raise ValueError(f"Invalid MCP server format: {server_str}. Expected: name=command [args...]")

            name, command_line = server_str.split("=", 1)
            name = name.strip()
            command_line = command_line.strip()

            if not name or not command_line:
                raise ValueError(f"Invalid MCP server format: {server_str}")

            parts = command_line.split()
            command = parts[0]
            args = parts[1:] if len(parts) > 1 else []

            self.servers[name] = MCPServerConfig(name, command, args)

    def get_server(self, name: str) -> Optional[MCPServerConfig]:
        """Get configuration for a specific server."""
        return self.servers.get(name)

    def get_all_servers(self) -> Dict[str, MCPServerConfig]:
        """Get all server configurations."""
        return self.servers

    def __repr__(self):
        return f"MCPConfig(servers={list(self.servers.keys())})"

    def format_for_debug(self, config_file: Optional[str] = None) -> str:
        """Format loaded configuration for debug output.

        Args:
            config_file: Optional file path to include in output

        Returns:
            Formatted string with config details
        """
        lines = []

        if config_file:
            lines.append(f"Config file: {Path(config_file).resolve()}")

        if self.servers:
            lines.append(f"Servers loaded: {len(self.servers)}")
            for name, config in self.servers.items():
                lines.append(f"  • {name}")
                lines.append(f"    command: {config.command}")
                if config.args:
                    args_str = " ".join(str(a) for a in config.args)
                    # Truncate very long arg strings
                    if len(args_str) > 100:
                        args_str = args_str[:97] + "..."
                    lines.append(f"    args: {args_str}")
                if config.env:
                    lines.append(f"    env vars: {', '.join(config.env.keys())}")
        else:
            lines.append("No servers configured")

        return "\n".join(lines)
