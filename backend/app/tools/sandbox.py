"""
The Docker sandbox.  OWNER: P4.  Backs run_python and sheet_op("compute").

THE RULE THAT IS NOT NEGOTIABLE: generated code never executes on the host.  If
Docker is unavailable, `run_python` returns an explicit
SANDBOX_UNAVAILABLE result.  There is no subprocess fallback in this file and
none may be added - a silent host-execution path would turn the strongest
security claim in the pitch into a lie.

WHAT DOCKER ISOLATION DOES AND DOES NOT COVER.  These flags isolate the
GENERATED CODE.  They say nothing about the SETU backend itself, which runs on
the host as an ordinary user process with access to the workspace and the audit
log.  Host-level isolation (a dedicated service account, an ACL-restricted
workspace, no interactive login) is a deployment requirement documented in
docs/ARCHITECTURE.md, not something the container flags provide.

THE IMAGE.  python:3.11-slim does NOT contain openpyxl or numpy, so
sheet_op("compute") fails immediately against the stock image.  sandbox/Dockerfile
in this repo builds `setu-sandbox:py311` with them pinned, strips pip so nothing
can be installed at runtime, and runs as 65534.  Build it AHEAD of time:

    docker build -t setu-sandbox:py311 sandbox/
    # or, offline:  docker load -i vendor/setu-sandbox-py311.tar

Packages are NEVER installed during a task.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

from ..config import Settings
from ..contracts import CodingOutput, ErrorCode
from ..security.paths import jail


_CLEANUP_TIMEOUT_S = 5
_PROCESS_STOP_TIMEOUT_S = 1
_RUN_TIMEOUT_GRACE_S = 5


def new_container_name() -> str:
    """Return a Docker-safe name unique to this server-side sandbox invocation."""
    return "setu-sbx-" + uuid.uuid4().hex


def build_command(
    settings: Settings,
    code_dir: Path,
    timeout_s: int,
    extra_mounts: Optional[list[tuple[Path, str]]] = None,
    *,
    container_name: Optional[str] = None,
) -> list[str]:
    """The nine controls, in one place, so the UI can print them verbatim.

    Rehearse naming three of these fluently (blueprint P4 role card).
    """
    cmd = [
        "docker", "run", "--rm",
        "--network=none",                       # 1. no interface exists inside
        "--read-only",                          # 2. immutable rootfs
        "--tmpfs", "/tmp:size=64m,noexec",      # 3. non-executable scratch
        "--memory=512m", "--memory-swap=512m",  # 4. no swap escape
        "--cpus=1",                             # 5. cpu bound
        "--pids-limit=64",                      # 6. fork-bomb resistant
        "--cap-drop=ALL",                       # 7. zero Linux capabilities
        "--security-opt", "no-new-privileges",  # 8. no setuid escalation
        "--user", "65534:65534",                # 9. runs as nobody
        "-v", str(code_dir) + ":/work:ro", "-w", "/work",
    ]
    if container_name:
        cmd += ["--name", container_name]
    for host_path, mount_at in extra_mounts or []:
        cmd += ["-v", str(host_path) + ":" + mount_at + ":ro"]
    # The image's ENTRYPOINT is ["python", "-B"], so the argument below is the
    # script to run, resolved against WORKDIR /work.  The wall-clock timeout is
    # enforced by the caller with asyncio.wait_for rather than by a `timeout`
    # binary, because the hardened image ships no coreutils.
    cmd += [settings.sandbox_image, "main.py"]
    return cmd


async def remove_container(container_name: str) -> None:
    """Best-effort, bounded cleanup of one known sandbox container.

    Docker reports an already-removed name as a non-zero exit.  That is still
    the desired state, so cleanup deliberately treats every Docker exit status
    as idempotent success.  It never enumerates or touches other containers.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "rm", "-f", container_name,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        # The primary timeout outcome must remain structured even if Docker
        # becomes unavailable while performing best-effort cleanup.
        return
    try:
        await asyncio.wait_for(proc.communicate(), timeout=_CLEANUP_TIMEOUT_S)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=1)
        except asyncio.TimeoutError:
            pass


def docker_available() -> tuple[bool, str]:
    if shutil.which("docker") is None:
        return False, "docker executable not found on PATH"
    return True, "docker binary present"


async def image_available(settings: Settings) -> tuple[bool, str]:
    ok, detail = docker_available()
    if not ok:
        return False, detail
    proc = await asyncio.create_subprocess_exec(
        "docker", "image", "inspect", settings.sandbox_image,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode == 0:
        return True, "image " + settings.sandbox_image + " present"
    return False, "image %s not built; run scripts/03_build_sandbox.ps1 (%s)" % (
        settings.sandbox_image, err.decode(errors="replace").strip()[:200],
    )


def unavailable_result(code: str, reason: str) -> CodingOutput:
    """The explicit 'we did not run this' result.  Never a fallback execution."""
    return CodingOutput(
        code=code,
        stdout="",
        stderr="SANDBOX_UNAVAILABLE: " + reason,
        exit_code=126,
        confidence=0.0,
        sandbox_available=False,
        sandbox_command=[],
    )


async def run_in_sandbox(
    code: str,
    settings: Settings,
    timeout_s: int = 15,
    input_paths: Optional[list[str]] = None,
    workspace_root: Optional[Path] = None,
) -> CodingOutput:
    """Execute `code` in the hardened container.  Never on the host.

    P4 TODO (acceptance: `run_python("print(2+2)")` returns stdout "4" with
    exit_code 0 on the demo laptop, and the printed command in the UI matches
    `build_command()` exactly):
      - stream stdout/stderr incrementally instead of buffering
      - map a container OOM kill (137) to a distinct, explained result
      - have P6 review the read-only workbook mount for sheet_op("compute")
    """
    # P1 supplies a per-task root once task workspaces are available. Until
    # then, retain the original settings.workspace behaviour. Resolve every
    # path before even probing Docker: invalid input must never invoke Docker.
    effective_root = workspace_root if workspace_root is not None else settings.workspace
    mounts: list[tuple[Path, str]] = []
    for rel in input_paths or []:
        host = jail(rel, effective_root)
        mounts.append((host, "/inputs/" + host.name))

    ok, detail = await image_available(settings)
    if not ok:
        return unavailable_result(code, detail)

    tmpdir = Path(tempfile.mkdtemp(prefix="setu_sbx_"))
    started = time.perf_counter()
    try:
        (tmpdir / "main.py").write_text(code, encoding="utf-8")

        container_name = new_container_name()
        cmd = build_command(
            settings, tmpdir, timeout_s, mounts, container_name=container_name
        )
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s + _RUN_TIMEOUT_GRACE_S
            )
            rc = proc.returncode or 0
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=_PROCESS_STOP_TIMEOUT_S)
            except asyncio.TimeoutError:
                pass
            await remove_container(container_name)
            return CodingOutput(
                code=code,
                stdout="",
                stderr="SANDBOX_TIMEOUT after %ss" % timeout_s,
                exit_code=124,
                confidence=0.0,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                sandbox_command=cmd,
            )
        return CodingOutput(
            code=code,
            stdout=out.decode("utf-8", errors="replace"),
            stderr=err.decode("utf-8", errors="replace"),
            exit_code=rc,
            confidence=1.0 if rc == 0 else 0.0,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            sandbox_command=cmd,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


SANDBOX_FLAG_NOTES = {
    "--network=none": "no network interface exists inside the container",
    "--read-only": "immutable root filesystem",
    "--tmpfs /tmp:size=64m,noexec": "64 MB non-executable scratch space",
    "--memory=512m --memory-swap=512m": "hard memory cap with no swap escape",
    "--cpus=1": "one CPU",
    "--pids-limit=64": "fork-bomb resistant",
    "--cap-drop=ALL": "zero Linux capabilities",
    "--security-opt no-new-privileges": "no setuid escalation",
    "--user 65534:65534": "runs as nobody",
}
_ = ErrorCode  # re-exported meaning for callers reading this module
