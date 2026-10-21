import subprocess
import sys


def test_chat_command_exposes_question_resume_and_index_options():
    result = subprocess.run(
        [sys.executable, "-m", "advanced_rag.agent.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert all(option in result.stdout for option in ["--question", "--session", "--persist-dir"])
