import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
MAX_TOOL_CALLS = 10


def safe_path(user_path: str) -> Path:
    target = (PROJECT_ROOT / user_path).resolve()
    if not str(target).startswith(str(PROJECT_ROOT)):
        raise ValueError("Path escapes project root")
    return target


def list_files(path: str) -> str:
    target = safe_path(path)
    if not target.exists():
        return f"Path does not exist: {path}"
    if not target.is_dir():
        return f"Not a directory: {path}"

    entries = sorted(p.name for p in target.iterdir())
    return "\n".join(entries)


def read_file(path: str) -> str:
    target = safe_path(path)
    if not target.exists():
        return f"Path does not exist: {path}"
    if not target.is_file():
        return f"Not a file: {path}"

    return target.read_text(encoding="utf-8")


TOOLS = {
    "list_files": list_files,
    "read_file": read_file,
}


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories at a relative path inside the project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path inside the project, for example 'wiki'.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file at a relative path inside the project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative file path inside the project, for example 'wiki/git-workflow.md'.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
]


SYSTEM_PROMPT = """You are a documentation agent for this repository.

Answer questions by reading the local documentation in the project, especially the wiki directory.

Rules:
- Use tools before answering if documentation is needed.
- Prefer starting with list_files on the wiki or a relevant subdirectory.
- Then use read_file on relevant files.
- Answer based on the documentation you found.
- Include a source field in the final JSON as a file path, optionally with a section anchor.
- Do not invent files or facts.
- Final output must be valid JSON with keys: answer, source, tool_calls.
"""


def call_llm(api_key: str, api_base: str, model: str, messages: list[dict]) -> dict:
    response = httpx.post(
        f"{api_base}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "tools": TOOL_SCHEMAS,
            "tool_choice": "auto",
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def main() -> int:
    load_dotenv(".env.agent.secret")

    api_key = os.getenv("LLM_API_KEY")
    api_base = os.getenv("LLM_API_BASE")
    model = os.getenv("LLM_MODEL")

    if not api_key or not api_base or not model:
        print("Missing LLM configuration in .env.agent.secret", file=sys.stderr)
        return 1

    if len(sys.argv) < 2:
        print('Usage: uv run agent.py "your question"', file=sys.stderr)
        return 1

    question = sys.argv[1]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    tool_calls_log = []

    try:
        for _ in range(MAX_TOOL_CALLS):
            data = call_llm(api_key, api_base, model, messages)
            message = data["choices"][0]["message"]

            if message.get("tool_calls"):
                assistant_tool_calls = message["tool_calls"]
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.get("content") or "",
                        "tool_calls": assistant_tool_calls,
                    }
                )

                for tool_call in assistant_tool_calls:
                    tool_name = tool_call["function"]["name"]
                    raw_args = tool_call["function"]["arguments"]
                    args = json.loads(raw_args)

                    if tool_name not in TOOLS:
                        result = f"Unknown tool: {tool_name}"
                    else:
                        try:
                            result = TOOLS[tool_name](**args)
                        except Exception as e:
                            result = f"Tool error: {e}"

                    tool_calls_log.append(
                        {
                            "tool": tool_name,
                            "args": args,
                            "result": result,
                        }
                    )

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": result,
                        }
                    )

                continue

            final_text = message.get("content", "").strip()

            try:
                parsed = json.loads(final_text)
                answer = parsed.get("answer", "")
                source = parsed.get("source", "")
            except json.JSONDecodeError:
                answer = final_text
                source = ""

            result = {
                "answer": answer,
                "source": source,
                "tool_calls": tool_calls_log,
            }

            print(json.dumps(result, ensure_ascii=False))
            return 0

        print(
            json.dumps(
                {
                    "answer": "Stopped after reaching the tool call limit.",
                    "source": "",
                    "tool_calls": tool_calls_log,
                },
                ensure_ascii=False,
            )
        )
        return 0

    except Exception as e:
        print(f"Agent error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())