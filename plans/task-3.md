# Task 3 Plan

## Goal
Extend the Task 2 agent with a new `query_api` tool so it can answer system questions using the running backend API.

## New tool
I will add `query_api(method, path, body=None)`.

## Authentication
The tool will send the backend API key using `LMS_API_KEY` from environment variables.

## API base URL
The tool will read `AGENT_API_BASE_URL` from environment variables.
If it is not set, it will default to `http://localhost:42002`.

## Prompt update
I will update the system prompt so the model:
- uses `read_file` and `list_files` for wiki and source-code questions,
- uses `query_api` for live system/data questions,
- combines tools when needed for bug diagnosis.

## Benchmark strategy
First I will implement the tool and run `uv run run_eval.py`.
Then I will inspect failing questions and improve the prompt and tool usage.