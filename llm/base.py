"""
Shared types and abstract base class for all LLM providers.

Tools are defined once in a neutral format (OpenAI-compatible JSON Schema).
Each provider adapter converts to its native format internally.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


# ── Neutral tool definition (define once, used by all providers) ──────────────
# Tools are plain dicts:
# {
#   "name": str,
#   "description": str,
#   "parameters": {          # JSON Schema object
#     "type": "object",
#     "properties": { ... },
#     "required": [ ... ]
#   }
# }
ToolDef = dict


@dataclass
class ToolCall:
    """A tool call requested by the LLM."""
    id: str
    name: str
    inputs: dict


@dataclass
class LLMResponse:
    """Normalised response from any LLM provider."""
    text: str | None          # Any text content in the response
    tool_calls: list[ToolCall] = field(default_factory=list)
    done: bool = False         # True = model finished, no more tool calls needed


class LLMProvider(ABC):
    """Abstract base — implement one method to add a new provider."""

    @abstractmethod
    def chat(
        self,
        system: str,
        messages: list[dict],   # [{role, content}] in neutral format
        tools: list[ToolDef],
    ) -> LLMResponse:
        """Send a conversation turn and return a normalised response."""
        ...

    def add_tool_results(
        self,
        messages: list[dict],
        response: LLMResponse,
        results: list[tuple[ToolCall, str]],  # [(tool_call, json_result_str)]
    ) -> list[dict]:
        """
        Append the assistant's response and tool results to the message list.
        Default implementation works for most providers — override if needed.
        """
        messages.append({"role": "assistant", "tool_calls": response.tool_calls, "_raw": response})
        messages.append({"role": "tool", "results": results})
        return messages
