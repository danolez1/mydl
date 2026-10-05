import os
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "hooks" / "step.sh"


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["HOOK_FORCE"] = "0"
    env.update(extra)
    return env


def git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo, env=clean_env(), check=True, capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("one\n")
    git(tmp_path, "add", "a.txt")
    git(tmp_path, "commit", "-qm", "one")
    return tmp_path


def step(repo, name, mode, command, *flags, **env):
    return subprocess.run(
        ["bash", str(SCRIPT), name, "--tree", mode, *flags, "--", "bash", "-c", command],
        cwd=repo, env=clean_env(**env), capture_output=True, text=True,
    )


def counter(repo):
    log = repo / "runs.log"
    return f"echo x >> {log}", lambda: len(log.read_text().splitlines()) if log.exists() else 0


def test_a_passed_step_is_skipped_on_the_same_tree(repo):
    cmd, runs = counter(repo)
    assert step(repo, "lint", "head", cmd).returncode == 0
    second = step(repo, "lint", "head", cmd)
    assert second.returncode == 0 and "already passed" in second.stdout
    assert runs() == 1


def test_a_changed_tree_runs_the_step_again(repo):
    cmd, runs = counter(repo)
    step(repo, "lint", "head", cmd)
    (repo / "a.txt").write_text("two\n")
    git(repo, "commit", "-qam", "two")
    step(repo, "lint", "head", cmd)
    assert runs() == 2


def test_a_failing_step_returns_its_code_and_leaves_no_stamp(repo):
    cmd, runs = counter(repo)
    assert step(repo, "bad", "head", "exit 7").returncode == 7
    assert step(repo, "bad", "head", cmd).returncode == 0
    assert runs() == 1
    assert "already passed" in step(repo, "bad", "head", cmd).stdout


def test_a_dirty_tree_records_no_stamp(repo):
    cmd, runs = counter(repo)
    (repo / "a.txt").write_text("dirty\n")
    first = step(repo, "lint", "head", cmd)
    assert "no stamp was recorded" in first.stdout
    step(repo, "lint", "head", cmd)
    assert runs() == 2


def test_hook_force_runs_a_stamped_step(repo):
    cmd, runs = counter(repo)
    step(repo, "lint", "head", cmd)
    step(repo, "lint", "head", cmd, HOOK_FORCE="1")
    assert runs() == 2


def test_a_stamp_older_than_the_ttl_is_ignored(repo):
    cmd, runs = counter(repo)
    step(repo, "audit", "head", cmd, "--ttl-hours", "1")
    stamp = next((repo / ".git" / "hook-stamps").iterdir())
    tree, _, rest = stamp.read_text().partition(" ")
    stamp.write_text(f"{tree} {int(time.time()) - 7200} none\n")
    step(repo, "audit", "head", cmd, "--ttl-hours", "1")
    assert runs() == 2


def test_bad_usage_is_refused(repo):
    assert subprocess.run(["bash", str(SCRIPT)], cwd=repo, capture_output=True).returncode != 0
    assert step(repo, "x", "nowhere", "true").returncode == 2
