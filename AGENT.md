# AGENT.md

## Overview
This agent answers repository documentation questions using an LLM and local file tools.

## LLM provider
Qwen Code API running on a VM.

## Model
qwen3-coder-plus

## Tools
The agent supports two tools:
- `list_files(path)` — lists files in a directory inside the project
- `read_file(path)` — reads a text file inside the project

## Safety
The agent only allows tool access inside the project root.
Paths are normalized and rejected if they escape the repository.

## How it works
1. The program reads the user question from the first CLI argument.
2. It loads LLM settings from `.env.agent.secret`.
3. It sends the question, system prompt, and tool schemas to the LLM.
4. If the LLM requests tools, the agent executes them.
5. Tool results are appended back into the conversation.
6. The loop continues until the model returns the final answer.

## Output
The program prints a single JSON object to stdout with:
- `answer`
- `source`
- `tool_calls`

## Example
```bash
uv run agent.py "How do you resolve a merge conflict?"