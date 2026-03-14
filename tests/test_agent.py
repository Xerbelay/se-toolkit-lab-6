import json
import subprocess


def run_agent(question: str) -> dict:
    result = subprocess.run(
        ["uv", "run", "agent.py", question],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_agent_outputs_valid_json():
    data = run_agent("What does REST stand for?")

    assert "answer" in data
    assert "tool_calls" in data
    assert isinstance(data["tool_calls"], list)


def test_agent_uses_read_file_for_merge_conflict_question():
    data = run_agent("How do you resolve a merge conflict?")

    assert "answer" in data
    assert "tool_calls" in data

    tool_names = [call["tool"] for call in data["tool_calls"]]
    assert "read_file" in tool_names


def test_agent_uses_list_files_for_wiki_listing_question():
    data = run_agent("What files are in the wiki?")

    assert "answer" in data
    assert "tool_calls" in data

    tool_names = [call["tool"] for call in data["tool_calls"]]
    assert "list_files" in tool_names


def test_agent_uses_read_file_for_framework_question():
    data = run_agent("What framework does the backend use?")

    assert "answer" in data
    assert "tool_calls" in data

    tool_names = [call["tool"] for call in data["tool_calls"]]
    assert "read_file" in tool_names


def test_agent_uses_query_api_for_item_count_question():
    data = run_agent("How many items are in the database?")

    assert "answer" in data
    assert "tool_calls" in data

    tool_names = [call["tool"] for call in data["tool_calls"]]
    assert "query_api" in tool_names