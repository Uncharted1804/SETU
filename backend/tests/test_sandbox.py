"""Focused P4 regression coverage for Docker sandbox lifecycle handling."""

from __future__ import annotations

import asyncio

import pytest

from app import config
from app.security.paths import PathEscape
from app.tools import sandbox


class _HangingDockerCli:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        await asyncio.Event().wait()
        return b"", b""

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or -9


class _CompletedDockerCli:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""


class _SuccessfulDockerCli(_CompletedDockerCli):
    async def communicate(self) -> tuple[bytes, bytes]:
        return b"ok\n", b""


async def _sandbox_is_available(_settings):
    return True, "image present"


def _mount_for(command: tuple[object, ...], target: str) -> str:
    marker = target + ":ro"
    return next(str(part) for part in command if str(part).endswith(marker))


@pytest.mark.asyncio
async def test_explicit_workspace_root_mounts_only_task_relative_input(monkeypatch, env, tmp_path):
    task_root = tmp_path / "task-a"
    source = task_root / "inputs" / "reading.csv"
    source.parent.mkdir(parents=True)
    source.write_text("reading\n12.4\n", encoding="utf-8")
    commands: list[tuple[object, ...]] = []

    async def fake_exec(*args, **kwargs):
        commands.append(args)
        return _SuccessfulDockerCli()

    monkeypatch.setattr(sandbox, "image_available", _sandbox_is_available)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    result = await sandbox.run_in_sandbox(
        "print('ok')", env, input_paths=["inputs/reading.csv"], workspace_root=task_root
    )

    assert result.exit_code == 0
    assert _mount_for(commands[0], "/inputs/reading.csv") == str(source.resolve()) + ":/inputs/reading.csv:ro"


@pytest.mark.asyncio
async def test_same_relative_input_is_resolved_per_workspace_root(monkeypatch, env, tmp_path):
    first_root = tmp_path / "task-a"
    second_root = tmp_path / "task-b"
    for root, content in ((first_root, "first"), (second_root, "second")):
        path = root / "inputs" / "data.txt"
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")
    commands: list[tuple[object, ...]] = []

    async def fake_exec(*args, **kwargs):
        commands.append(args)
        return _SuccessfulDockerCli()

    monkeypatch.setattr(sandbox, "image_available", _sandbox_is_available)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    for root in (first_root, second_root):
        result = await sandbox.run_in_sandbox(
            "print('ok')", env, input_paths=["inputs/data.txt"], workspace_root=root
        )
        assert result.exit_code == 0

    first_mount = _mount_for(commands[0], "/inputs/data.txt")
    second_mount = _mount_for(commands[1], "/inputs/data.txt")
    assert first_mount == str((first_root / "inputs" / "data.txt").resolve()) + ":/inputs/data.txt:ro"
    assert second_mount == str((second_root / "inputs" / "data.txt").resolve()) + ":/inputs/data.txt:ro"
    assert first_mount != second_mount


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/absolute.txt", "C:\\absolute.txt", "../outside.txt", "inputs/../../outside.txt"])
async def test_invalid_input_path_is_rejected_before_any_docker_command(monkeypatch, env, tmp_path, path):
    task_root = tmp_path / "task"
    task_root.mkdir()

    async def docker_must_not_run(*args, **kwargs):
        raise AssertionError("invalid input path must not invoke Docker")

    async def image_probe_must_not_run(_settings):
        raise AssertionError("invalid input path must not even inspect Docker")

    monkeypatch.setattr(sandbox, "image_available", image_probe_must_not_run)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", docker_must_not_run)

    with pytest.raises(PathEscape):
        await sandbox.run_in_sandbox(
            "print('never runs')", env, input_paths=[path], workspace_root=task_root
        )


@pytest.mark.asyncio
async def test_none_workspace_root_retains_settings_workspace_mount(monkeypatch, env):
    source = env.workspace / "inputs" / "legacy.txt"
    source.parent.mkdir(parents=True)
    source.write_text("legacy", encoding="utf-8")
    commands: list[tuple[object, ...]] = []

    async def fake_exec(*args, **kwargs):
        commands.append(args)
        return _SuccessfulDockerCli()

    monkeypatch.setattr(sandbox, "image_available", _sandbox_is_available)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    result = await sandbox.run_in_sandbox(
        "print('ok')", env, input_paths=["inputs/legacy.txt"], workspace_root=None
    )

    assert result.exit_code == 0
    assert _mount_for(commands[0], "/inputs/legacy.txt") == str(source.resolve()) + ":/inputs/legacy.txt:ro"


@pytest.mark.asyncio
async def test_timeout_kills_docker_and_removes_only_its_named_container(monkeypatch, env):
    """A timed-out CLI gets an exact, bounded `docker rm -f <name>` cleanup."""
    name = "setu-sbx-test-timeout"
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    runner = _HangingDockerCli()

    async def image_present(_settings):
        return True, "image present"

    async def fake_exec(*args, **kwargs):
        calls.append((args, kwargs))
        if args[:3] == ("docker", "rm", "-f"):
            # Docker uses a non-zero code when the container is already gone;
            # that is an idempotent cleanup success.
            return _CompletedDockerCli(returncode=1)
        return runner

    monkeypatch.setattr(sandbox, "image_available", image_present)
    monkeypatch.setattr(sandbox, "new_container_name", lambda: name)
    monkeypatch.setattr(sandbox, "_CLEANUP_TIMEOUT_S", 0.1)
    monkeypatch.setattr(sandbox, "_RUN_TIMEOUT_GRACE_S", 0)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    result = await sandbox.run_in_sandbox("import time; time.sleep(30)", env, timeout_s=0)

    assert result.exit_code == 124
    assert result.stderr == "SANDBOX_TIMEOUT after 0s"
    assert runner.killed is True
    assert result.sandbox_command[result.sandbox_command.index("--name") + 1] == name
    assert [call[0] for call in calls] == [
        tuple(result.sandbox_command),
        ("docker", "rm", "-f", name),
    ]


async def _container_exists(container_name: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "docker", "container", "inspect", container_name,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()
    return proc.returncode == 0


async def _require_real_docker(settings) -> None:
    available, detail = await sandbox.image_available(settings)
    if not available:
        pytest.skip("real Docker sandbox unavailable: " + detail)


@pytest.mark.asyncio
async def test_real_docker_timeout_removes_the_exact_named_container(env):
    """Integration check; skipped rather than simulated when Docker is unavailable."""
    await _require_real_docker(env)

    result = await sandbox.run_in_sandbox("import time; time.sleep(30)", env, timeout_s=1)
    name = result.sandbox_command[result.sandbox_command.index("--name") + 1]

    assert result.exit_code == 124
    assert result.stderr == "SANDBOX_TIMEOUT after 1s"
    assert await _container_exists(name) is False


@pytest.mark.asyncio
async def test_real_docker_success_self_removes_named_container(env):
    """`--rm` still performs normal successful-execution cleanup."""
    await _require_real_docker(env)

    result = await sandbox.run_in_sandbox("print(2 + 2)", env, timeout_s=1)
    name = result.sandbox_command[result.sandbox_command.index("--name") + 1]

    assert result.exit_code == 0
    assert result.stdout == "4\n"
    assert await _container_exists(name) is False
