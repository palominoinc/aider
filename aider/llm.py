import importlib
import os
import warnings
from phoenix.otel import register  # Phoenix tracer registration
from aider.dump import dump  # noqa: F401


from openinference.instrumentation import using_session
from openinference.semconv.trace import SpanAttributes
from opentelemetry import trace
import uuid

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

AIDER_SITE_URL = "https://aider.chat"
AIDER_APP_NAME = "Aider"
os.environ["OR_SITE_URL"] = AIDER_SITE_URL
os.environ["OR_APP_NAME"] = AIDER_APP_NAME
os.environ["LITELLM_MODE"] = "PRODUCTION"


PHOENIX_ENABLED = os.environ.get("AIDER_PHOENIX_ENABLED", "false").lower() == "true"
PHOENIX_ENDPOINT = os.environ.get("AIDER_PHOENIX_ENDPOINT", "http://localhost:6006/v1/traces")


VERBOSE = False

class LazyLiteLLM:
    _lazy_module = None
    _phoenix_initialized = False 

    def __getattr__(self, name):
        if name == "_lazy_module":
            return super()
        self._load_litellm()
        return getattr(self._lazy_module, name)

    def _load_litellm(self):
        if self._lazy_module is not None:
            return
        if VERBOSE:
            print("Loading litellm...")

        if PHOENIX_ENABLED and not self._phoenix_initialized:
            try:
                from openinference.instrumentation.litellm import LiteLLMInstrumentor

                tracer_provider = register(
                    project_name="aider",
                    endpoint=PHOENIX_ENDPOINT,
                )
                # Instrument LiteLLM
                LiteLLMInstrumentor().instrument(tracer_provider=tracer_provider)
                self._phoenix_initialized = True
                print("Phoenix instrumentation enabled")
            except ImportError:
                print("Phoenix dependencies not installed. Install with:")
                print("pip install arize-phoenix-otel openinference-instrumentation-litellm")
        self._lazy_module = importlib.import_module("litellm")
        self._lazy_module.suppress_debug_info = True
        self._lazy_module.set_verbose = False
        self._lazy_module.drop_params = True
        self._lazy_module._logging._disable_debugging()

        if os.environ.get("LUNARY_PUBLIC_KEY"):
            self._lazy_module.success_callback = ["lunary"]
            self._lazy_module.failure_callback = ["lunary"]

litellm = LazyLiteLLM()
__all__ = [litellm]