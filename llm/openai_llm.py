"""
OpenAI provider (also works with any OpenAI-compatible API endpoint).
"""
import json

from openai import OpenAI

from .base import LLMProvider, LLMResponse, ToolCall, ToolDef


class OpenAIProvider(LLMProvider):

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(self, system: str, messages: list[dict], tools: list[ToolDef]) -> LLMResponse:
        openai_messages = _to_openai_messages(messages, system)
        openai_tools = [{"type": "function", "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["parameters"],
        }} for t in tools]

        response = self._client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            tools=openai_tools or None,
            max_tokens=8192,
            temperature=0.2,
        )

        msg = response.choices[0].message
        text = msg.content
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    inputs=json.loads(tc.function.arguments),
                ))

        done = response.choices[0].finish_reason == "stop" or not tool_calls
        resp = LLMResponse(text=text, tool_calls=tool_calls, done=done)
        resp._openai_message = msg
        return resp

    def add_tool_results(self, messages, response, results):
        msg = response._openai_message
        messages.append({"role": "assistant", "_openai_message": msg})
        for tc, result_str in results:
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})
        return messages


def _to_openai_messages(messages: list[dict], system: str) -> list:
    result = [{"role": "system", "content": system}]
    for m in messages:
        if m["role"] == "user":
            result.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            if "_openai_message" in m:
                msg = m["_openai_message"]
                entry = {"role": "assistant", "content": msg.content}
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in msg.tool_calls
                    ]
                result.append(entry)
        elif m["role"] == "tool":
            result.append({"role": "tool",
                           "tool_call_id": m["tool_call_id"],
                           "content": m["content"]})
    return result
