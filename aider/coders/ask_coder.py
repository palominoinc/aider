from .ask_prompts import AskPrompts
from .base_coder import Coder


class AskCoder(Coder):
    """Ask questions about code without making any changes."""

    edit_format = "ask"
    functions = []  # Enable MCP tool addition when --enable-mcp is set
    gpt_prompts = AskPrompts()
