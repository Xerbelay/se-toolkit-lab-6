# Task 2 Plan

## Goal
Upgrade the Task 1 CLI into a documentation agent with tool use.

## Tools
I will implement two tools:
- list_files(path) to inspect folders in the repository
- read_file(path) to read wiki files

## Security
Both tools will only allow paths inside the project root.
I will normalize the path and reject traversal like ../.

## Agentic loop
1. Send the user question, system prompt, and tool schemas to the LLM.
2. If the LLM returns tool calls, execute them.
3. Append tool results back into the conversation.
4. Repeat until the LLM returns the final answer.
5. Stop after at most 10 tool calls.

## Output
The agent will print JSON with:
- answer
- source
- tool_calls

## Prompt strategy
The system prompt will tell the model to:
- first inspect the wiki with list_files
- then read relevant documentation with read_file
- answer using the docs
- include the source as file-path#section-anchor