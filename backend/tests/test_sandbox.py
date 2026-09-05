"""Focused P4 regression coverage for Docker sandbox lifecycle handling."""

from __future__ import annotations

import asyncio

import pytest

from app import config
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
