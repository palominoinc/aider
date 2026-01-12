from .ask_prompts import AskPrompts
from .base_coder import Coder


class AskCoder(Coder):
    """Ask questions about code without making any changes."""

    edit_format = "ask"
    gpt_prompts = AskPrompts()

    def __init__(self, *args, **kwargs):
        # Initialize instance variable for functions (not class variable)
        self.functions = []
        super().__init__(*args, **kwargs)
