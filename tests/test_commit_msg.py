import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "hooks" / "commit-msg.sh"


def check(tmp_path, message):
    file = tmp_path / "MSG"
    file.write_text(message)
    return subprocess.run(["bash", str(SCRIPT), str(file)], capture_output=True, text=True).returncode


@pytest.mark.parametrize("message", ["fix(utils): remove a nested quantifier\n\nBody.\n", "feat!: drop the old route\n", "\n# comment\nci: add a gate\n"])
def test_a_conventional_subject_passes(tmp_path, message):
    assert check(tmp_path, message) == 0


@pytest.mark.parametrize("message", ["Update the readme\n", "build: add a thing\n", "fix: \n", "fix: " + "a" * 100 + "\n"])
def test_a_bad_subject_is_refused(tmp_path, message):
    assert check(tmp_path, message) == 1


@pytest.mark.parametrize("trailer", ["Co-Authored-By: Someone <a@b.c>", "Generated with a tool"])
def test_attribution_trailers_are_refused(tmp_path, trailer):
    assert check(tmp_path, f"fix: a change\n\n{trailer}\n") == 1
