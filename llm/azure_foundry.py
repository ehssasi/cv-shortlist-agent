"""
Azure AI Foundry provider — uses anthropic.AnthropicFoundry (SDK native).
Authenticates via Azure CLI token provider. SSL verification disabled for
Grundfos corporate proxy.
"""
import subprocess
import httpx
import anthropic

from .base import LLMProvider, LLMResponse, ToolCall, ToolDef


def _az_token_provider() -> str:
    """Returns a fresh Azure AD bearer token via az CLI.
    Uses 'az.cmd' on Windows and 'az' on Linux/WSL."""
    import platform
    az = "az.cmd" if platform.system() == "Windows" else "az"
    return subprocess.check_output(
        [az, "account", "get-access-token",
         "--resource", "https://cognitiveservices.azure.com",
         "--query", "accessToken", "-o", "tsv"],
        text=True,
    ).strip()


class AzureFoundryProvider(LLMProvider):

    def __init__(self, resource: str, model: str):
        self.model = model
        self._client = anthropic.AnthropicFoundry(
            resource=resource,
            azure_ad_token_provider=_az_token_provider,
            http_client=httpx.Client(verify=False),  # Grundfos corporate proxy
        )

    def chat(self, system: str, messages: list[dict], tools: list[ToolDef]) -> LLMResponse:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=system,
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

        resp = LLMResponse(
            text=text,
            tool_calls=tool_calls,
            done=response.stop_reason == "end_turn" or not tool_calls,
        )
        resp._raw = response
        return resp

    def add_tool_results(self, messages, response, results):
        messages.append({"role": "assistant", "_anthropic_content": response._raw.content})
        messages.append({"role": "tool", "_anthropic_tool_results": [
            {"type": "tool_result", "tool_use_id": tc.id, "content": result_str}
            for tc, result_str in results
        ]})
        return messages


def _tool_to_anthropic(tool: ToolDef) -> dict:
    return {
        "name": tool["name"],
        "description": tool["description"],
        "input_schema": tool["parameters"],
    }


def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
    result = []
    for m in messages:
        if m["role"] == "user":
            result.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            if "_anthropic_content" in m:
                result.append({"role": "assistant", "content": m["_anthropic_content"]})
        elif m["role"] == "tool":
            result.append({"role": "user", "content": m["_anthropic_tool_results"]})
    return result
