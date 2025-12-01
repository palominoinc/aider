# MCP Integration in Aider

## Overview

Aider now supports integration with Model Context Protocol (MCP) servers, allowing the AI assistant to access external tools and data sources during conversations. MCP is a standardized protocol for connecting AI applications to various tools, databases, and services.

With MCP integration enabled, the LLM has access to tools provided by MCP servers and can call them as needed to help with your requests. Tool results are automatically fed back into the conversation context.

## What is MCP?

The Model Context Protocol (MCP) is an open protocol developed by Anthropic that enables AI applications to securely connect to external data sources and tools. MCP servers expose tools, resources, and prompts that LLMs can use to extend their capabilities.

Examples of MCP servers:
- **Filesystem servers** - Read/write files, list directories
- **Database servers** - Query databases (PostgreSQL, SQLite, etc.)
- **API servers** - Interact with GitHub, Slack, Google Drive, etc.
- **Custom servers** - Any tool you build following the MCP specification

## Installation

The MCP Python SDK is included as a dependency:

```bash
pip install -r requirements.txt
```

Or install directly:

```bash
pip install mcp>=1.22.0
```

## Configuration

### Enabling MCP

MCP integration is **opt-in** and disabled by default. Enable it with the `--enable-mcp` flag:

```bash
aider --enable-mcp
```

### Configuring MCP Servers

There are two ways to configure MCP servers:

#### Option 1: Configuration File (Recommended)

Create a `.aider.mcp.yml` file in your project directory:

```yaml
servers:
  filesystem:
    command: "npx"
    args:
      - "-y"
      - "@modelcontextprotocol/server-filesystem"
      - "${PWD}"  # Allow access to current directory

  github:
    command: "mcp-server-github"
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"

  postgres:
    command: "mcp-server-postgres"
    args:
      - "postgresql://localhost/mydb"
    env:
      PGPASSWORD: "${DB_PASSWORD}"
```

Then run aider with:

```bash
aider --enable-mcp --mcp-config .aider.mcp.yml
```

**Configuration file features:**
- Environment variable expansion with `${VAR_NAME}` syntax
- Multiple servers in one file
- Server-specific environment variables
- Command arguments as lists

#### Option 2: Command Line Arguments

Configure servers directly via CLI:

```bash
aider --enable-mcp \
  --mcp-servers "filesystem=npx -y @modelcontextprotocol/server-filesystem /tmp" \
  --mcp-servers "github=mcp-server-github"
```

The format is: `name=command [args...]`

You can use `--mcp-servers` multiple times to add multiple servers.

#### Option 3: Combined Approach

You can combine both methods - servers from the config file will be loaded first, then CLI servers will be added:

```bash
aider --enable-mcp --mcp-config .aider.mcp.yml --mcp-servers "custom=my-tool"
```

### Configuration in .aider.conf.yml

You can also set MCP options in your main aider configuration file:

```yaml
# Enable MCP integration
enable-mcp: true

# Specify MCP config file
mcp-config: .aider.mcp.yml

# Or specify servers inline
mcp-servers:
  - "filesystem=npx -y @modelcontextprotocol/server-filesystem /tmp"
  - "github=mcp-server-github"
```

## Usage

Once MCP is enabled and servers are configured, the LLM automatically has access to their tools. You don't need to do anything special - just ask the LLM to perform tasks that require those tools.

### Example Session

```bash
$ aider --enable-mcp --mcp-config .aider.mcp.yml --verbose

Connected to 2 MCP server(s), 15 tool(s) available

> Can you check if there are any TODO comments in the codebase and create GitHub issues for them?

Calling MCP tool: mcp_filesystem_search_files
MCP tool executed successfully

Calling MCP tool: mcp_github_create_issue
MCP tool executed successfully

I found 3 TODO comments and created GitHub issues #123, #124, #125 for them.
```

### How It Works

1. **Startup**: When aider starts with `--enable-mcp`, it connects to configured MCP servers
2. **Tool Discovery**: Aider queries each server for available tools
3. **Schema Conversion**: Tool schemas are converted to OpenAI function calling format
4. **LLM Integration**: Tools are registered with the LLM as available functions
5. **Execution**: When the LLM calls a tool, aider executes it via the MCP server
6. **Results**: Tool results are added to the conversation for the LLM to use

### Verbose Mode

Use `--verbose` to see detailed MCP activity:

```bash
aider --enable-mcp --mcp-config .aider.mcp.yml --verbose
```

This shows:
- Server connection status
- Number of tools discovered
- Tool execution logs
- MCP errors and warnings

## How MCP Changes the Program

### Architecture Changes

#### 1. New Components

**MCPService** (`aider/mcp_service.py`)
- Orchestrates multiple MCP server connections
- Manages tool discovery and schema aggregation
- Routes tool execution calls to appropriate servers
- Handles lifecycle (startup, shutdown, error recovery)

**MCPClient** (`aider/mcp_client.py`)
- Synchronous wrapper around the async MCP SDK
- Runs event loop in background thread per server
- Bridges sync aider code with async MCP protocol
- Uses `asyncio.run_coroutine_threadsafe()` for thread-safe async calls

**MCPConfig** (`aider/mcp_config.py`)
- Loads server configurations from YAML files and CLI args
- Handles environment variable expansion (`${VAR}` syntax)
- Validates configuration structure

#### 2. Integration Points

**Main Loop** (`aider/main.py`)
- MCP service initialized before Coder creation (line ~973)
- Cleanup in finally block ensures graceful shutdown
- Error handling allows continuing without MCP if initialization fails

**Coder Class** (`aider/coders/base_coder.py`)
- New `mcp_service` parameter passed to all Coders
- Tool schema augmentation after function validation (line ~548)
- MCP tools added to `self.functions` list for LLM

**Tool Execution** (`aider/coders/base_coder.py`)
- `apply_updates()` intercepts MCP tool calls (line ~2378)
- `_execute_mcp_tool()` handles execution and error handling
- `_add_tool_result_to_chat()` formats results for conversation

### Execution Flow

```
┌─────────────────────────────────────────────────────────────┐
│ STARTUP                                                     │
│ 1. Parse --enable-mcp and --mcp-config flags               │
│ 2. Create MCPService with configuration                    │
│ 3. MCPService.start_servers()                              │
│    - Creates MCPClient for each server                     │
│    - Starts background thread with event loop              │
│    - Connects via stdio transport                          │
│ 4. MCPService.discover_tools()                             │
│    - Queries each server for available tools               │
│    - Stores tool schemas indexed by server                 │
│ 5. Pass mcp_service to Coder.create()                      │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ CODER INITIALIZATION                                        │
│ 1. Coder.__init__ stores mcp_service reference             │
│ 2. Validate existing self.functions schemas                │
│ 3. If mcp_service exists:                                  │
│    - Get tool schemas from MCPService                      │
│    - Convert MCP format → OpenAI function format           │
│    - Extend self.functions with MCP tools                  │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ CONVERSATION LOOP                                           │
│ 1. User sends message                                       │
│ 2. Coder.send_message() formats context                    │
│ 3. LLM receives message + available functions              │
│ 4. LLM responds (content or tool call)                     │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ MCP TOOL EXECUTION (if LLM calls MCP tool)                 │
│ 1. apply_updates() detects tool name starts with "mcp_"    │
│ 2. _execute_mcp_tool() extracts tool name and arguments    │
│ 3. MCPService.execute_tool()                               │
│    - Finds correct server for tool                         │
│    - MCPClient.call_tool() (sync wrapper)                  │
│    - asyncio.run_coroutine_threadsafe() to event loop      │
│    - MCP SDK executes tool on server                       │
│    - Result returned through Future                        │
│ 4. _add_tool_result_to_chat() formats result               │
│    - Adds assistant message with tool_calls                │
│    - Adds tool message with result                         │
│ 5. Return to conversation loop                             │
│    - Next send_message() includes tool result              │
│    - LLM processes result and continues                    │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ SHUTDOWN                                                    │
│ 1. User exits aider (Ctrl-D or /exit)                      │
│ 2. finally block in main()                                 │
│ 3. MCPService.shutdown()                                   │
│    - MCPClient.disconnect() for each server                │
│    - Async cleanup via event loop                          │
│    - Stop event loop thread                                │
│    - Clean up resources                                    │
└─────────────────────────────────────────────────────────────┘
```

### Threading Model

MCP integration uses a threading-based approach to bridge async and sync code:

```
┌──────────────────────────────────────────────────────────┐
│ Main Thread (Synchronous)                                │
│                                                           │
│  ┌─────────────┐                                         │
│  │   Aider     │                                         │
│  │   Main      │                                         │
│  │   Loop      │                                         │
│  └──────┬──────┘                                         │
│         │                                                 │
│         │ MCPService.execute_tool() [sync]               │
│         ↓                                                 │
│  ┌──────────────┐                                        │
│  │  MCPClient   │                                        │
│  │  (sync API)  │                                        │
│  └──────┬───────┘                                        │
│         │                                                 │
│         │ asyncio.run_coroutine_threadsafe()             │
└─────────┼─────────────────────────────────────────────────┘
          │
          │ Submit coroutine to event loop
          │
┌─────────▼─────────────────────────────────────────────────┐
│ Background Thread (Per Server)                            │
│                                                           │
│  ┌──────────────┐                                        │
│  │  Event Loop  │                                        │
│  │  (asyncio)   │                                        │
│  └──────┬───────┘                                        │
│         │                                                 │
│         │ await session.call_tool()                      │
│         ↓                                                 │
│  ┌──────────────┐                                        │
│  │ MCP Session  │                                        │
│  │ (async API)  │                                        │
│  └──────┬───────┘                                        │
│         │                                                 │
│         │ stdio transport                                │
│         ↓                                                 │
│  ┌──────────────┐                                        │
│  │ MCP Server   │                                        │
│  │ (subprocess) │                                        │
│  └──────────────┘                                        │
└───────────────────────────────────────────────────────────┘
```

**Key benefits:**
- Keeps main UI thread responsive
- Isolates async complexity to background threads
- Each server gets dedicated event loop (no cross-contamination)
- Future-based API allows waiting for results synchronously

### Tool Naming Convention

MCP tools are namespaced to prevent conflicts with aider's built-in functions:

**Format**: `mcp_{server_name}_{tool_name}`

Examples:
- `mcp_filesystem_read_file` - Read file via filesystem server
- `mcp_github_create_issue` - Create GitHub issue
- `mcp_postgres_query` - Run SQL query

The LLM sees these as available functions and can call them by name. The `mcp_` prefix triggers special handling in `apply_updates()`.

### Error Handling

MCP integration uses graceful degradation:

**Startup Errors**:
- Configuration file not found → Error, prompt to continue without MCP
- Server fails to start → Log error, continue with other servers
- No servers connect → Warning, aider runs normally without MCP

**Runtime Errors**:
- Tool execution fails → Error returned to LLM in tool result
- Server disconnects → Error message, could add reconnection logic (future)
- Invalid tool arguments → Validation error returned to LLM

**All errors are non-fatal** - aider continues working, just without MCP functionality.

### Schema Conversion

MCP tool schemas are converted to OpenAI function calling format:

**MCP Schema**:
```json
{
  "name": "read_file",
  "description": "Read contents of a file",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": {"type": "string", "description": "File path"}
    },
    "required": ["path"]
  }
}
```

**Converted to OpenAI Format**:
```json
{
  "name": "mcp_filesystem_read_file",
  "description": "Read contents of a file",
  "parameters": {
    "type": "object",
    "properties": {
      "path": {"type": "string", "description": "File path"}
    },
    "required": ["path"]
  }
}
```

The conversion happens in `MCPService.get_tool_schemas()`.

### Compatibility

**No Breaking Changes**:
- MCP is opt-in (default: disabled)
- Existing functionality unchanged when MCP is disabled
- No new required dependencies for non-MCP users
- All existing edit formats work normally

**Works With**:
- All aider edit formats (whole file, unified diff, etc.)
- All LLM providers (OpenAI, Anthropic, etc.) that support function calling
- Git workflows, auto-commits, testing, linting
- Existing commands and features

**Limitations**:
- Only function-calling capable models can use MCP tools
- Tools must return serializable results (JSON)
- No streaming support for tool results (tools execute fully then return)

## Troubleshooting

### MCP servers not connecting

**Check server command is accessible**:
```bash
which npx
npx --version
```

**Test server manually**:
```bash
npx -y @modelcontextprotocol/server-filesystem /tmp
```

**Use verbose mode**:
```bash
aider --enable-mcp --mcp-config .aider.mcp.yml --verbose
```

### Tools not appearing

**Verify servers connected**:
- Look for "Connected to X server(s)" message at startup
- Use `--verbose` to see tool discovery

**Check configuration**:
- Ensure YAML syntax is valid
- Verify command paths are correct
- Check environment variables are set

### Tool execution fails

**Common issues**:
- Insufficient permissions (filesystem access, API tokens)
- Invalid arguments (check tool schema requirements)
- Server crash or disconnect (check server logs)

**Debug steps**:
1. Run with `--verbose` to see detailed error messages
2. Test the MCP server independently
3. Check server documentation for tool requirements

## Examples

### Example 1: Filesystem Access

Enable the filesystem MCP server:

```yaml
# .aider.mcp.yml
servers:
  filesystem:
    command: "npx"
    args:
      - "-y"
      - "@modelcontextprotocol/server-filesystem"
      - "/home/user/projects"
```

```bash
aider --enable-mcp --mcp-config .aider.mcp.yml
```

Now the LLM can read files outside the current chat context:

```
> Can you check what's in the config directory?
> Read the contents of ../other-project/README.md
```

### Example 2: GitHub Integration

```yaml
# .aider.mcp.yml
servers:
  github:
    command: "mcp-server-github"
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
```

```bash
export GITHUB_TOKEN="ghp_xxxxx"
aider --enable-mcp --mcp-config .aider.mcp.yml
```

The LLM can now interact with GitHub:

```
> Create a GitHub issue for this bug
> What are the open pull requests?
> Add a comment to issue #42
```

### Example 3: Database Queries

```yaml
# .aider.mcp.yml
servers:
  postgres:
    command: "mcp-server-postgres"
    args:
      - "postgresql://localhost:5432/mydb"
    env:
      PGPASSWORD: "${DB_PASSWORD}"
```

```
> Show me the schema of the users table
> How many active users do we have?
> Find all orders from the last week
```

## Security Considerations

1. **Tool Access**: MCP tools run with your user permissions - be cautious what servers you enable
2. **Environment Variables**: Secrets in config files should use `${VAR}` expansion, not hardcoded values
3. **Filesystem Access**: Limit filesystem server to specific directories
4. **API Tokens**: Use read-only tokens when possible
5. **Network Access**: Be aware of what external services MCP servers can access

## Further Reading

- [Official MCP Documentation](https://modelcontextprotocol.io/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Available MCP Servers](https://github.com/modelcontextprotocol/servers)
- [Building Custom MCP Servers](https://modelcontextprotocol.io/quickstart/server)

## Contributing

The MCP integration is implemented in MVP scope with basic functionality. Future enhancements could include:

- `/mcp-tools` and `/mcp-servers` commands for introspection
- Automatic server reconnection on disconnect
- Server health monitoring
- Tool usage analytics
- Permission system for tool execution
- Tool result caching
- Support for MCP resources and prompts (not just tools)

Contributions welcome! See the implementation plan in `/root/.claude/plans/lazy-noodling-fairy.md`.
