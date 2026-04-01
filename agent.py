"""
CV Shortlist Agent — provider-agnostic agentic loop.
The LLM provider is selected entirely from config.yaml.
"""
import json

from llm.factory import load_provider
from prompts import SYSTEM_PROMPT
from tools.cv_parser import list_cvs, parse_cv
from tools.linkedin import close_browser, find_similar_profiles, get_linkedin_profile, search_linkedin_profile
from tools.report import save_report

# ── Tool definitions (neutral JSON Schema — provider-independent) ─────────────
ALL_TOOLS = [
    {
        "name": "list_cvs",
        "description": "List all CV files in a folder. Call this first to discover available CVs.",
        "parameters": {
            "type": "object",
            "properties": {
                "folder_path": {"type": "string", "description": "Path to the folder containing CV files"},
            },
            "required": ["folder_path"],
        },
    },
    {
        "name": "read_cv",
        "description": "Extract text from a single CV file (PDF, DOCX, TXT). Do NOT call on job description files.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Full path to the CV file"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "search_linkedin_profile",
        "description": "Search LinkedIn for a candidate by name and optional company/role.",
        "parameters": {
            "type": "object",
            "properties": {
                "name":    {"type": "string", "description": "Full name of the candidate"},
                "company": {"type": "string", "description": "Current or most recent company (optional)"},
                "role":    {"type": "string", "description": "Current or most recent job title (optional)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_linkedin_profile",
        "description": "Get detailed info from a LinkedIn profile URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "LinkedIn profile URL"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "find_similar_profiles",
        "description": "Find LinkedIn profiles similar to a given profile URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "url":         {"type": "string", "description": "LinkedIn profile URL"},
                "max_results": {"type": "integer", "description": "Max profiles to return (default 5)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "save_report",
        "description": "Save the final shortlist report as markdown and Word document. Call once all CVs are scored.",
        "parameters": {
            "type": "object",
            "properties": {
                "report_data": {
                    "type": "object",
                    "description": "Full report data",
                    "properties": {
                        "job_title":  {"type": "string"},
                        "summary":    {"type": "string", "description": "Executive summary paragraph"},
                        "shortlist": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name":                {"type": "string"},
                                    "score":               {"type": "integer"},
                                    "cv_file":             {"type": "string"},
                                    "current_role":        {"type": "string"},
                                    "linkedin_url":        {"type": "string"},
                                    "linkedin_confidence": {"type": "string"},
                                    "linkedin_validation": {"type": "string"},
                                    "strengths":           {"type": "array", "items": {"type": "string"}},
                                    "gaps":                {"type": "array", "items": {"type": "string"}},
                                },
                            },
                        },
                        "similar_profiles": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name":     {"type": "string"},
                                    "headline": {"type": "string"},
                                    "location": {"type": "string"},
                                    "url":      {"type": "string"},
                                    "source":   {"type": "string"},
                                },
                            },
                        },
                        "next_steps": {"type": "string"},
                    },
                    "required": ["job_title", "summary", "shortlist"],
                },
                "output_dir": {"type": "string", "description": "Directory to save report"},
            },
            "required": ["report_data"],
        },
    },
]

LINKEDIN_TOOLS = {"search_linkedin_profile", "get_linkedin_profile", "find_similar_profiles"}


# ── Tool executor (provider-independent) ─────────────────────────────────────
def execute_tool(name: str, inputs: dict) -> str:
    print(f"  [tool] {name}({', '.join(f'{k}={repr(v)[:60]}' for k, v in inputs.items())})")
    if name == "list_cvs":
        result = list_cvs(inputs["folder_path"])
    elif name == "read_cv":
        result = parse_cv(inputs["file_path"])
    elif name == "search_linkedin_profile":
        result = search_linkedin_profile(inputs["name"], inputs.get("company", ""), inputs.get("role", ""))
    elif name == "get_linkedin_profile":
        result = get_linkedin_profile(inputs["url"])
    elif name == "find_similar_profiles":
        result = find_similar_profiles(inputs["url"], inputs.get("max_results", 5))
    elif name == "save_report":
        result = save_report(inputs["report_data"], inputs.get("output_dir", "output"))
    else:
        result = {"error": f"Unknown tool: {name}"}
    return json.dumps(result, ensure_ascii=False)


# ── Agent loop ────────────────────────────────────────────────────────────────
def run_agent(
    cv_folder: str,
    job_description: str,
    criteria: str,
    top_n: int = 5,
    output_dir: str = "output",
    use_linkedin: bool = True,
    config_path: str | None = None,
):
    provider, provider_name = load_provider(config_path)

    active_tools = ALL_TOOLS if use_linkedin else [t for t in ALL_TOOLS if t["name"] not in LINKEDIN_TOOLS]

    initial_message = f"""
Please shortlist the top {top_n} candidates from the CVs in this folder: {cv_folder}

IMPORTANT: The folder may contain a job description file (filename contains 'Job Description').
Do NOT read it as a CV — skip it entirely.

## Job Description
{job_description}

## Additional Criteria
{criteria}

## Instructions
1. Use list_cvs to discover all files, then read_cv for each CV (skip any job description files)
2. Score and rank all candidates 0-100 against the job description and criteria
3. Shortlist the top {top_n} with strengths and gaps for each
{"4. Search LinkedIn to validate each shortlisted candidate and find 3-5 similar profiles" if use_linkedin else "4. Skip LinkedIn (disabled for this run)"}
5. Call save_report with the complete results (output_dir: {output_dir})

Begin now.
"""

    print(f"\n{'='*60}")
    print(f"CV Shortlist Agent  |  Provider: {provider_name}")
    print(f"Folder: {cv_folder}  |  Top {top_n}  |  LinkedIn: {'on' if use_linkedin else 'off'}")
    print(f"{'='*60}\n")

    messages = [{"role": "user", "content": initial_message}]

    try:
        while True:
            response = provider.chat(SYSTEM_PROMPT, messages, active_tools)

            if response.text:
                print(f"\n[Agent] {response.text[:400]}{'...' if len(response.text) > 400 else ''}")

            if response.done or not response.tool_calls:
                print("\n[Agent] Task complete.")
                break

            # Execute all tool calls
            results = []
            for tc in response.tool_calls:
                result_str = execute_tool(tc.name, tc.inputs)
                results.append((tc, result_str))

            # Let the provider append response + results in its own format
            messages = provider.add_tool_results(messages, response, results)

    finally:
        if use_linkedin:
            close_browser()
