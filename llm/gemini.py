"""
Google Gemini provider.
Requires GEMINI_API_KEY or key set in config.
"""
import json

from google import genai
from google.genai import types

from .base import LLMProvider, LLMResponse, ToolCall, ToolDef

# Map JSON Schema types to Gemini types
_TYPE_MAP = {
    "string": types.Type.STRING,
    "integer": types.Type.INTEGER,
    "number": types.Type.NUMBER,
    "boolean": types.Type.BOOLEAN,
    "array": types.Type.ARRAY,
    "object": types.Type.OBJECT,
}


def _schema_to_gemini(schema: dict) -> types.Schema:
    t = _TYPE_MAP.get(schema.get("type", "string"), types.Type.STRING)
    kwargs = {"type": t}

    if "description" in schema:
        kwargs["description"] = schema["description"]
    if "properties" in schema:
        kwargs["properties"] = {k: _schema_to_gemini(v) for k, v in schema["properties"].items()}
    if "required" in schema:
        kwargs["required"] = schema["required"]
    if "items" in schema:
        kwargs["items"] = _schema_to_gemini(schema["items"])

    return types.Schema(**kwargs)


def _tool_to_gemini(tool: ToolDef) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=tool["name"],
        description=tool["description"],
        parameters=_schema_to_gemini(tool["parameters"]),
    )


class GeminiProvider(LLMProvider):

    def __init__(self, api_key: str, model: str):
        self.model = model
        self._client = genai.Client(api_key=api_key)

    def chat(self, system: str, messages: list[dict], tools: list[ToolDef]) -> LLMResponse:
        gemini_tools = [types.Tool(function_declarations=[_tool_to_gemini(t) for t in tools])]
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=gemini_tools,
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="AUTO")
            ),
            max_output_tokens=8192,
            temperature=0.2,
        )

        history = _to_gemini_messages(messages)
        response = self._client.models.generate_content(
            model=self.model,
            contents=history,
            config=config,
        )

        candidate = response.candidates[0]
        text = None
        tool_calls = []

        for part in candidate.content.parts:
            if part.text:
                text = part.text
            elif part.function_call:
                fc = part.function_call
                tool_calls.append(ToolCall(id=fc.name, name=fc.name, inputs=dict(fc.args)))

        done = not tool_calls
        # Stash raw content for use in add_tool_results
        resp = LLMResponse(text=text, tool_calls=tool_calls, done=done)
        resp._gemini_content = candidate.content
        return resp

    def add_tool_results(self, messages, response, results):
        messages.append({"role": "assistant", "_gemini_content": response._gemini_content})
        messages.append({"role": "tool", "_gemini_results": [
            types.Part(function_response=types.FunctionResponse(
                name=tc.name,
                response=json.loads(result_str) if isinstance(result_str, str) else result_str,
            ))
            for tc, result_str in results
        ]})
        return messages


def _to_gemini_messages(messages: list[dict]):
    result = []
    for m in messages:
        if m["role"] == "user":
            result.append(types.Content(role="user", parts=[types.Part(text=m["content"])]))
        elif m["role"] == "assistant":
            if "_gemini_content" in m:
                result.append(m["_gemini_content"])
        elif m["role"] == "tool":
            result.append(types.Content(role="user", parts=m["_gemini_results"]))
    return result
