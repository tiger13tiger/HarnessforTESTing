"""Proves the auto-push helper against a real (throwaway) git repo -- no Synapse
connection or LLM call involved, just the git plumbing."""
import os
import subprocess

from harness.evolve_cli import _commit_and_push


def _run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo_with_remote(tmp_path):
    remote = tmp_path / "remote.git"
    _run(["git", "init", "--bare", str(remote)], cwd=tmp_path)

    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "config", "user.name", "Test"], cwd=repo)
    _run(["git", "remote", "add", "origin", str(remote)], cwd=repo)

    proc_file = repo / "sp.sql"
    proc_file.write_text("CREATE OR ALTER PROCEDURE dbo.sp_x\nAS\nBEGIN\n  SELECT 1;\nEND\n")
    _run(["git", "add", "sp.sql"], cwd=repo)
    _run(["git", "commit", "-m", "init"], cwd=repo)
    _run(["git", "branch", "-M", "main"], cwd=repo)
    _run(["git", "push", "-u", "origin", "main"], cwd=repo)
    return repo, proc_file


def test_pushes_when_the_file_actually_changed(tmp_path):
    repo, proc_file = _init_repo_with_remote(tmp_path)
    proc_file.write_text("CREATE OR ALTER PROCEDURE dbo.sp_x\nAS\nBEGIN\n  SELECT 2;\nEND\n")

    old_cwd = os.getcwd()
    os.chdir(repo)
    try:
        pushed = _commit_and_push(proc_file, "test commit")
    finally:
        os.chdir(old_cwd)

    assert pushed is True
    log = subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=repo, capture_output=True, text=True, check=True)
    assert log.stdout.strip() == "test commit"


def test_is_a_noop_when_nothing_changed(tmp_path):
    repo, proc_file = _init_repo_with_remote(tmp_path)

    old_cwd = os.getcwd()
    os.chdir(repo)
    try:
        pushed = _commit_and_push(proc_file, "test commit")
    finally:
        os.chdir(old_cwd)

    assert pushed is False
