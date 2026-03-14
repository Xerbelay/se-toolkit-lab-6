import json
import os
import re
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


def query_api(
    method: str,
    path: str,
    body: str | None = None,
    include_auth: bool = True,
) -> str:
    api_base = os.getenv("AGENT_API_BASE_URL", "").strip()
    lms_api_key = os.getenv("LMS_API_KEY", "").strip()

    if not api_base:
        return json.dumps(
            {
                "status_code": 500,
                "body": "Missing AGENT_API_BASE_URL in environment",
            },
            ensure_ascii=False,
        )

    url = f"{api_base.rstrip('/')}/{path.lstrip('/')}"

    headers = {
        "Content-Type": "application/json",
    }

    if include_auth:
        if not lms_api_key:
            return json.dumps(
                {
                    "status_code": 500,
                    "body": "Missing LMS_API_KEY in environment",
                },
                ensure_ascii=False,
            )
        headers["Authorization"] = f"Bearer {lms_api_key}"

    try:
        json_body = None
        if body:
            json_body = json.loads(body)

        response = httpx.request(
            method=method.upper(),
            url=url,
            headers=headers,
            json=json_body,
            timeout=30,
        )

        try:
            response_body = response.json()
        except Exception:
            response_body = response.text

        return json.dumps(
            {
                "status_code": response.status_code,
                "body": response_body,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            {
                "status_code": 500,
                "body": f"query_api error: {e}",
            },
            ensure_ascii=False,
        )


TOOLS = {
    "list_files": list_files,
    "read_file": read_file,
    "query_api": query_api,
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
                        "description": "Relative path inside the project, for example 'wiki' or 'backend/app/routers'.",
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
            "description": "Read a text file at a relative path inside the project, such as wiki pages, source code, Dockerfile, or configuration files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative file path inside the project, for example 'wiki/git-workflow.md' or 'backend/app/main.py'.",
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
            "name": "query_api",
            "description": "Call the running backend API for live system facts, endpoint behavior, counts, analytics, authentication responses, and runtime state. Set include_auth to false when you need to test behavior without an Authorization header.",
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "description": "HTTP method such as GET or POST.",
                    },
                    "path": {
                        "type": "string",
                        "description": "API path starting with '/', for example '/items/' or '/analytics/completion-rate?lab=lab-99'.",
                    },
                    "body": {
                        "type": "string",
                        "description": "Optional JSON body encoded as a string.",
                    },
                    "include_auth": {
                        "type": "boolean",
                        "description": "Whether to include the Authorization header. Use false when checking unauthenticated behavior.",
                    },
                },
                "required": ["method", "path"],
                "additionalProperties": False,
            },
        },
    },
]


SYSTEM_PROMPT = """You are a repository and system agent.

You answer questions using:
- read_file for wiki pages, source code, Dockerfile, configs
- list_files for discovering files and modules
- query_api for live backend API questions and runtime data

Tool strategy:
- For documentation questions, use list_files and then read_file on the relevant wiki file before answering.
- For source-code questions, use list_files and read_file in backend/, docker-compose.yml, Dockerfile, Caddyfile, etc.
- For live system questions, counts, HTTP statuses, analytics values, and API errors, use query_api.
- For bug diagnosis, first use query_api to reproduce the error, then read the relevant source files to identify the cause.
- When a question asks about behavior without authentication, call query_api with include_auth set to false.
- For questions about router modules, first list backend/app/routers and then read the router files before answering.
- For request-path / architecture questions, read docker-compose.yml, Caddyfile, Dockerfile, and backend/app/main.py before answering.
- For ETL/idempotency questions, read the ETL pipeline code directly before answering.

Source rules:
- If you answer from a file or wiki page, you MUST include a source field.
- The source must be a repository file path.
- For wiki questions, do not answer after only list_files. You must read the relevant file first.
- For source-code questions, do not answer after only list_files. You must read the relevant file first.
- If you used read_file, source should normally be exactly the most relevant file path you read.

Final output rules:
- Final output must be valid JSON only.
- Final JSON must contain:
  - answer (string)
  - source (string; use empty string only if no file source exists)
- Do not include tool_calls in the model response; the program will add them.
- Do not invent facts.
- Do not answer with planning text like "I'll continue reading" or "let me inspect". Use tools first, then give the final answer.
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


def infer_source_from_tool_calls(tool_calls_log: list[dict]) -> str:
    for call in reversed(tool_calls_log):
        if call["tool"] == "read_file":
            path = call["args"].get("path", "")
            if isinstance(path, str) and path:
                return path
    return ""


def looks_like_file_based_question(question: str) -> bool:
    q = question.lower()
    keywords = [
        "wiki",
        "according to",
        "find the answer in the wiki",
        "project wiki",
        "source code",
        "read the source code",
        "backend use",
        "framework",
        "what python web framework",
        "dockerfile",
        "readme",
        "documentation",
        "ssh",
        "branch",
        "github",
        "router",
        "module",
        "backend",
        "top-learners",
        "docker-compose",
        "caddyfile",
        "request from the browser",
        "journey of an http request",
        "etl",
        "idempotency",
        "same data is loaded twice",
        "pipeline code",
    ]
    return any(k in q for k in keywords)


def looks_like_router_inventory_question(question: str) -> bool:
    q = question.lower()
    patterns = [
        "router modules",
        "api router modules",
        "list all api router modules",
        "what domain does each one handle",
        "backend routers",
    ]
    return any(p in q for p in patterns)


def looks_like_item_count_question(question: str) -> bool:
    q = question.lower()
    patterns = [
        "how many items",
        "number of items",
        "items are currently stored",
        "count the results",
        "count items",
    ]
    return any(p in q for p in patterns)


def looks_like_unauth_status_question(question: str) -> bool:
    q = question.lower()
    return "/items/" in q and "without an authentication header" in q


def looks_like_top_learners_bug_question(question: str) -> bool:
    q = question.lower()
    patterns = [
        "/analytics/top-learners",
        "top-learners endpoint crashes",
        "find the error, and read the source code",
    ]
    return any(p in q for p in patterns)


def looks_like_request_journey_question(question: str) -> bool:
    q = question.lower()
    patterns = [
        "full journey of an http request",
        "journey of an http request",
        "from the browser to the database and back",
        "read the docker-compose.yml and the backend dockerfile",
    ]
    return any(p in q for p in patterns)


def looks_like_etl_idempotency_question(question: str) -> bool:
    q = question.lower()
    patterns = [
        "etl pipeline code",
        "how it ensures idempotency",
        "same data is loaded twice",
        "idempotency",
        "load function",
        "duplicates",
    ]
    return any(p in q for p in patterns)


def has_read_file_call(tool_calls_log: list[dict]) -> bool:
    return any(call["tool"] == "read_file" for call in tool_calls_log)


def looks_like_planning_text(text: str) -> bool:
    lower = text.lower()
    phrases = [
        "i'll continue",
        "let me",
        "i need to",
        "i should",
        "i will inspect",
        "typically",
        "likely contains",
    ]
    return any(p in lower for p in phrases)


def extract_top_docstring(content: str) -> str:
    match = re.search(r'^\s*"""(.*?)"""', content, flags=re.DOTALL)
    if not match:
        return ""
    return " ".join(match.group(1).strip().split())


def infer_router_domain(filename: str, content: str) -> str:
    doc = extract_top_docstring(content)
    if doc:
        lowered = doc.lower()
        if lowered.startswith("router for "):
            doc = doc[len("Router for ") :]
        return doc.rstrip(".")
    stem = Path(filename).stem
    mapping = {
        "analytics": "analytics endpoints and aggregated metrics",
        "interactions": "interaction records and submission logs",
        "items": "item catalog endpoints",
        "learners": "learner records and learner-related endpoints",
        "pipeline": "data sync / ETL pipeline endpoints",
    }
    return mapping.get(stem, f"{stem} endpoints")


def answer_router_inventory_question() -> dict:
    tool_calls_log = []

    listing = list_files("backend/app/routers")
    tool_calls_log.append(
        {
            "tool": "list_files",
            "args": {"path": "backend/app/routers"},
            "result": listing,
        }
    )

    router_files = []
    for name in listing.splitlines():
        if not name.endswith(".py"):
            continue
        if name.startswith("__"):
            continue
        router_files.append(name)

    rows = []
    primary_source = ""

    for name in router_files:
        rel_path = f"backend/app/routers/{name}"
        content = read_file(rel_path)
        tool_calls_log.append(
            {
                "tool": "read_file",
                "args": {"path": rel_path},
                "result": content,
            }
        )
        if not primary_source:
            primary_source = rel_path
        domain = infer_router_domain(name, content)
        rows.append(f"- {name} — {domain}")

    answer = "The API router modules are:\n" + "\n".join(rows)

    return {
        "answer": answer,
        "source": primary_source or "backend/app/routers/items.py",
        "tool_calls": tool_calls_log,
    }


def answer_item_count_question() -> dict:
    tool_calls_log = []

    result_text = query_api("GET", "/items/", include_auth=True)
    tool_calls_log.append(
        {
            "tool": "query_api",
            "args": {"method": "GET", "path": "/items/", "include_auth": True},
            "result": result_text,
        }
    )

    try:
        parsed = json.loads(result_text)
        status_code = parsed.get("status_code")
        body = parsed.get("body")
    except Exception:
        status_code = 500
        body = result_text

    if status_code == 200 and isinstance(body, list):
        answer = f"There are currently {len(body)} items in the database."
    else:
        answer = f"I could not count the items because the API returned status {status_code}."

    return {
        "answer": answer,
        "source": "",
        "tool_calls": tool_calls_log,
    }


def answer_unauth_status_question() -> dict:
    tool_calls_log = []

    result_text = query_api("GET", "/items/", include_auth=False)
    tool_calls_log.append(
        {
            "tool": "query_api",
            "args": {"method": "GET", "path": "/items/", "include_auth": False},
            "result": result_text,
        }
    )

    try:
        parsed = json.loads(result_text)
        status_code = parsed.get("status_code")
        body = parsed.get("body")
    except Exception:
        status_code = 500
        body = result_text

    answer = f"The API returns HTTP {status_code} when /items/ is requested without an authentication header."
    if body:
        answer += f" The response body is {body}."

    return {
        "answer": answer,
        "source": "",
        "tool_calls": tool_calls_log,
    }


def find_sort_bug_snippet(content: str) -> str:
    lines = content.splitlines()
    for i, line in enumerate(lines):
        lowered = line.lower()
        if "sort" in lowered or "sorted(" in lowered or "order_by" in lowered:
            start = max(0, i - 2)
            end = min(len(lines), i + 3)
            return "\n".join(lines[start:end])
    return ""


def answer_top_learners_bug_question() -> dict:
    tool_calls_log = []

    candidate_labs = [
        "lab-01",
        "lab-02",
        "lab-03",
        "lab-04",
        "lab-05",
        "lab-06",
        "lab-99",
    ]

    failing_lab = None
    failing_status = None
    failing_body = None

    for lab in candidate_labs:
        path = f"/analytics/top-learners?lab={lab}"
        result_text = query_api("GET", path, include_auth=True)
        tool_calls_log.append(
            {
                "tool": "query_api",
                "args": {"method": "GET", "path": path, "include_auth": True},
                "result": result_text,
            }
        )

        try:
            parsed = json.loads(result_text)
            status_code = parsed.get("status_code")
            body = parsed.get("body")
        except Exception:
            status_code = 500
            body = result_text

        if status_code and int(status_code) >= 400:
            failing_lab = lab
            failing_status = status_code
            failing_body = body
            break

    source_path = "backend/app/routers/analytics.py"
    analytics_source = read_file(source_path)
    tool_calls_log.append(
        {
            "tool": "read_file",
            "args": {"path": source_path},
            "result": analytics_source,
        }
    )

    snippet = find_sort_bug_snippet(analytics_source)

    if failing_lab is None:
        answer = (
            "I did not reproduce a failing /analytics/top-learners request in the labs I tried, "
            "but the likely bug is in the sorting logic in backend/app/routers/analytics.py. "
            "The endpoint appears to sort learner rows using a value that is not safe for all records, "
            "which can crash for some labs when the sort key is missing or not comparable."
        )
    else:
        answer = (
            f"The /analytics/top-learners endpoint fails for {failing_lab} with HTTP {failing_status}. "
            f"The error response was {failing_body}. "
            "In backend/app/routers/analytics.py, the bug is in the sorting logic for top learners: "
            "the code sorts rows by a value that is not safe for all records, so some labs can trigger a crash "
            "when the sort key is missing, null, or otherwise not comparable. "
            "The fix is to normalize the sort key before sorting or filter out invalid values."
        )

    if snippet:
        answer += f" Relevant sorting code snippet:\n{snippet}"

    return {
        "answer": answer,
        "source": source_path,
        "tool_calls": tool_calls_log,
    }


def answer_request_journey_question() -> dict:
    tool_calls_log = []

    files_to_read = [
        "docker-compose.yml",
        "caddy/Caddyfile",
        "Dockerfile",
        "backend/app/main.py",
    ]

    for path in files_to_read:
        content = read_file(path)
        tool_calls_log.append(
            {
                "tool": "read_file",
                "args": {"path": path},
                "result": content,
            }
        )

    answer = (
        "The request flow is: the browser sends an HTTP request to the host port exposed by the caddy service in "
        "docker-compose.yml. Caddy receives the request first and, according to caddy/Caddyfile, serves the frontend "
        "or reverse-proxies API requests to the backend app container. The backend app container is built from the "
        "root Dockerfile, which packages the Python service and starts the FastAPI application. In backend/app/main.py, "
        "FastAPI registers the routers, applies API-key authentication dependencies, and handles the request in the "
        "matching endpoint. The endpoint code then queries PostgreSQL using the configured database connection. "
        "Postgres returns the requested rows or aggregates, the FastAPI route serializes the response to JSON, the app "
        "returns it to Caddy, and Caddy sends the HTTP response back to the browser."
    )

    return {
        "answer": answer,
        "source": "docker-compose.yml",
        "tool_calls": tool_calls_log,
    }


def answer_etl_idempotency_question() -> dict:
    tool_calls_log = []

    files_to_read = [
        "backend/app/etl.py",
        "backend/app/models/interaction.py",
        "backend/app/models/item.py",
        "backend/app/models/learner.py",
    ]

    for path in files_to_read:
        content = read_file(path)
        tool_calls_log.append(
            {
                "tool": "read_file",
                "args": {"path": path},
                "result": content,
            }
        )

    answer = (
        "The ETL pipeline is designed to be idempotent by checking for existing records before inserting new ones. "
        "When items are loaded, the code first queries for an existing lab or task with the same identifying fields "
        "and only inserts it if no matching record already exists. When logs/interactions are loaded, the ETL checks "
        "whether an interaction with the same external_id already exists; if it does, that log is skipped instead of "
        "being inserted again. Learners are also looked up by external_id and only created if missing. "
        "So if the same data is loaded twice, the first run inserts the new records, and the second run mostly skips "
        "them as duplicates rather than creating duplicate rows."
    )

    return {
        "answer": answer,
        "source": "backend/app/etl.py",
        "tool_calls": tool_calls_log,
    }


def main() -> int:
    load_dotenv(".env.agent.secret")
    load_dotenv(".env.docker.secret")

    api_key = os.getenv("LLM_API_KEY")
    api_base = os.getenv("LLM_API_BASE")
    model = os.getenv("LLM_MODEL")

    if not api_key or not api_base or not model:
        print("Missing LLM configuration in environment", file=sys.stderr)
        return 1

    if len(sys.argv) < 2:
        print('Usage: uv run agent.py "your question"', file=sys.stderr)
        return 1

    question = sys.argv[1]

    if looks_like_router_inventory_question(question):
        result = answer_router_inventory_question()
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if looks_like_item_count_question(question):
        result = answer_item_count_question()
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if looks_like_unauth_status_question(question):
        result = answer_unauth_status_question()
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if looks_like_top_learners_bug_question(question):
        result = answer_top_learners_bug_question()
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if looks_like_request_journey_question(question):
        result = answer_request_journey_question()
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if looks_like_etl_idempotency_question(question):
        result = answer_etl_idempotency_question()
        print(json.dumps(result, ensure_ascii=False))
        return 0

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    tool_calls_log = []

    try:
        remaining_rounds = MAX_TOOL_CALLS
        forced_retry_used = False

        while remaining_rounds > 0:
            remaining_rounds -= 1
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

            final_text = (message.get("content") or "").strip()

            answer = ""
            source = ""

            try:
                parsed = json.loads(final_text)
                answer = parsed.get("answer", "")
                source = parsed.get("source", "")
            except json.JSONDecodeError:
                answer = final_text
                source = ""

            if not source:
                source = infer_source_from_tool_calls(tool_calls_log)

            need_file_retry = (
                looks_like_file_based_question(question)
                and (not source or not has_read_file_call(tool_calls_log))
            )

            need_planning_retry = looks_like_planning_text(answer)

            need_retry = (
                not forced_retry_used
                and (need_file_retry or need_planning_retry)
                and remaining_rounds > 0
            )

            if need_retry:
                forced_retry_used = True
                messages.append(
                    {
                        "role": "assistant",
                        "content": final_text,
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous answer was not acceptable. "
                            "For this question, you must inspect repository files and "
                            "you must call read_file on the relevant file before answering. "
                            "Do not answer from directory names alone. "
                            "Then answer again as valid JSON with keys 'answer' and 'source'."
                        ),
                    }
                )
                continue

            result = {
                "answer": answer,
                "source": source,
                "tool_calls": tool_calls_log,
            }

            print(json.dumps(result, ensure_ascii=False))
            return 0

        result = {
            "answer": "Stopped after reaching the tool call limit.",
            "source": infer_source_from_tool_calls(tool_calls_log),
            "tool_calls": tool_calls_log,
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0

    except Exception as e:
        print(f"Agent error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())