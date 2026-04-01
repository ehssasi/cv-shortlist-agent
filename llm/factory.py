"""
Reads config.yaml and returns the configured LLM provider.
Resolves ${ENV_VAR} placeholders in config values.
"""
import os
import re
import pathlib
import yaml

from .base import LLMProvider


def _resolve(value: str) -> str:
    """Replace ${VAR_NAME} with the environment variable value."""
    if not isinstance(value, str):
        return value
    def replacer(match):
        var = match.group(1)
        val = os.environ.get(var, "")
        if not val:
            print(f"  [config] WARNING: env var ${var} is not set")
        return val
    return re.sub(r'\$\{(\w+)\}', replacer, value)


def load_provider(config_path: str | None = None) -> tuple[LLMProvider, str]:
    """
    Load provider from config.yaml.
    Returns (provider_instance, provider_name).
    """
    if config_path is None:
        config_path = pathlib.Path(__file__).parent.parent / "config.yaml"

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    provider_name = cfg.get("provider", "azure_foundry")
    provider_cfg = cfg.get(provider_name, {})

    # Resolve env var placeholders
    resolved = {k: _resolve(v) for k, v in provider_cfg.items()}

    print(f"  [config] Provider: {provider_name}  |  Model: {resolved.get('model', '?')}")

    if provider_name == "azure_foundry":
        from .azure_foundry import AzureFoundryProvider
        resource = resolved.get("resource") or os.environ.get("ANTHROPIC_FOUNDRY_RESOURCE", "")
        model    = resolved.get("model")    or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6")
        return AzureFoundryProvider(resource=resource, model=model), provider_name

    elif provider_name == "gemini":
        from .gemini import GeminiProvider
        api_key = resolved.get("api_key") or os.environ.get("GEMINI_API_KEY", "")
        model   = resolved.get("model", "gemini-2.0-flash")
        return GeminiProvider(api_key=api_key, model=model), provider_name

    elif provider_name == "openai":
        from .openai_llm import OpenAIProvider
        api_key  = resolved.get("api_key") or os.environ.get("OPENAI_API_KEY", "")
        model    = resolved.get("model", "gpt-4o")
        base_url = resolved.get("base_url")  # optional for custom endpoints
        return OpenAIProvider(api_key=api_key, model=model, base_url=base_url), provider_name

    elif provider_name == "anthropic":
        from .azure_foundry import AzureFoundryProvider
        # Re-use the same Anthropic SDK adapter but pointed at api.anthropic.com
        import anthropic
        api_key = resolved.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        model   = resolved.get("model", "claude-sonnet-4-6")
        # Patch: create a direct Anthropic client (no Azure base_url)
        from .base import LLMProvider, LLMResponse, ToolCall
        import httpx

        class DirectAnthropicProvider(LLMProvider):
            def __init__(self):
                self._client = anthropic.Anthropic(api_key=api_key)
                self.model = model

            def chat(self, system, messages, tools):
                from .azure_foundry import _to_anthropic_messages, _tool_to_anthropic
                response = self._client.messages.create(
                    model=self.model, max_tokens=8192, system=system,
                    tools=[_tool_to_anthropic(t) for t in tools],
                    messages=_to_anthropic_messages(messages),
                )
                text = None
                tool_calls = []
                for block in response.content:
                    if hasattr(block, "text"):
                        text = block.text
                    elif block.type == "tool_use":
                        tool_calls.append(ToolCall(id=block.id, name=block.name, inputs=dict(block.input)))
                resp = LLMResponse(text=text, tool_calls=tool_calls, done=not tool_calls or response.stop_reason == "end_turn")
                resp._raw = response
                return resp

            def add_tool_results(self, messages, response, results):
                from .azure_foundry import AzureFoundryProvider
                return AzureFoundryProvider.add_tool_results(self, messages, response, results)

        return DirectAnthropicProvider(), provider_name

    else:
        raise ValueError(f"Unknown provider: {provider_name}. Choose from: azure_foundry, gemini, openai, anthropic")
