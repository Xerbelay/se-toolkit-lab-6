# AGENT.md

## Overview
This project contains a CLI agent that answers questions about the repository and the running system. It uses an LLM with tool calling and an agent loop. The agent can inspect documentation, read source code, list directories, and query the live backend API.

## LLM provider
The agent uses the Qwen Code API through an OpenAI-compatible endpoint.

## Model
The default model is `qwen3-coder-plus`.

## Tools
The agent supports three tools:

- `list_files(path)` — lists files and directories inside the project
- `read_file(path)` — reads text files inside the project
- `query_api(method, path, body=None)` — sends authenticated HTTP requests to the running backend API

## Authentication
The LLM provider credentials are loaded from environment variables:
- `LLM_API_KEY`
- `LLM_API_BASE`
- `LLM_MODEL`

The backend API key is loaded from:
- `LMS_API_KEY`

The backend base URL is loaded from:
- `AGENT_API_BASE_URL`

If `AGENT_API_BASE_URL` is not set, the agent defaults to `http://localhost:42002`.

## Safety
File tools only allow access inside the repository root. Paths are resolved and rejected if they escape the project directory. This prevents path traversal like `../`.

## Tool routing strategy
The system prompt tells the model to choose tools based on the question type:

- For wiki and documentation questions, use `read_file` and sometimes `list_files`
- For source-code and architecture questions, use `list_files` and `read_file`
- For runtime, status-code, analytics, and count questions, use `query_api`
- For bug diagnosis, first call `query_api` to reproduce the problem, then inspect the relevant source files with `read_file`

## Agent loop
The program sends the user question, tool schemas, and system prompt to the LLM. If the model returns tool calls, the agent executes them and appends the tool results back into the conversation. This loop continues until the model returns the final answer. The loop is limited to 10 tool-call rounds to avoid infinite loops.

## Output
The program prints a single JSON object to stdout. It always includes:
- `answer`
- `tool_calls`

It may also include:
- `source`

## Lessons learned
The main challenge is not the API call itself, but teaching the model when to use the right tool. Good tool descriptions and a clear system prompt are important. Another challenge is bug-diagnosis questions: the agent has to reproduce the error first, then inspect the source code. This task showed how an agent becomes much more useful when it can combine documentation lookup, source inspection, and live system queries instead of relying only on static text.