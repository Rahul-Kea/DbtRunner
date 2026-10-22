from __future__ import annotations

import asyncio
import atexit
import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

# Ensure src/ is importable
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dbt_runner.config import PROJECT_ROOT
from dbt_runner.validation import discover_incremental_models

app = FastAPI(title="dbt Runner API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOADS_DIR = PROJECT_ROOT / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
RUN_LOGS_DIR = PROJECT_ROOT / "run_logs"
RUN_LOGS_DIR.mkdir(parents=True, exist_ok=True)
CONTAINER_RUNS_DIR = PROJECT_ROOT / "container_runs"
CONTAINER_RUNS_DIR.mkdir(parents=True, exist_ok=True)
RUN_IMAGE = "dbt-runner-execution:local"

# In-memory tracking of active/recent runs
RUNS_IN_FLIGHT: dict[str, dict[str, Any]] = {}
RUN_SESSIONS: dict[str, dict[str, Any]] = {}
SESSION_IDLE_TTL_SECONDS = 90

SHELL_SESSIONS: dict[str, dict[str, Any]] = {}
SHELL_SESSION_LOCK = asyncio.Lock()
RUN_IMAGE_BUILD_LOCK = threading.Lock()
DOCKER_EXECUTABLE = shutil.which("docker")
RUN_IMAGE_BUILT = False


def _extract_zip(zip_path: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    root = target_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            normalized = member.filename.replace("\\", "/")
            member_path = Path(normalized)
            destination = (root / member_path).resolve()
            if member_path.is_absolute() or ".." in member_path.parts or not destination.is_relative_to(root):
                continue
            if stat.S_ISLNK(member.external_attr >> 16):
                continue
            zf.extract(member, root)


def normalize_git_url(raw_url: str, branch_override: str | None = None) -> tuple[str, str | None, str | None]:
    """
    Normalizes a git URL which may be a browser web URL (GitHub, GitLab, Bitbucket)
    pointing to a specific branch and/or subfolder.

    Returns:
        (clone_url, branch, subpath)
    """
    url = raw_url.strip().rstrip("/")
    subpath: str | None = None
    branch = branch_override.strip() if branch_override and branch_override.strip() else None

    # GitHub web URLs: https://github.com/:owner/:repo/(tree|blob)/:branch(/:subpath)
    gh_match = re.match(r"^https?://github\.com/([^/]+)/([^/]+)/(?:tree|blob)/([^/]+)(?:/(.*))?/?$", url)
    if gh_match:
        owner, repo, gh_branch, gh_subpath = gh_match.groups()
        clone_url = f"https://github.com/{owner}/{repo.removesuffix('.git')}.git"
        branch = branch or gh_branch
        subpath = gh_subpath or None
        return clone_url, branch, subpath

    # GitLab web URLs: https://gitlab.com/:owner/:repo/-/tree/:branch(/:subpath)
    gl_match = re.match(r"^https?://gitlab\.com/([^/]+)/([^/]+)/-/tree/([^/]+)(?:/(.*))?/?$", url)
    if gl_match:
        owner, repo, gl_branch, gl_subpath = gl_match.groups()
        clone_url = f"https://gitlab.com/{owner}/{repo.removesuffix('.git')}.git"
        branch = branch or gl_branch
        subpath = gl_subpath or None
        return clone_url, branch, subpath

    # Bitbucket web URLs: https://bitbucket.org/:owner/:repo/src/:branch(/:subpath)
    bb_match = re.match(r"^https?://bitbucket\.org/([^/]+)/([^/]+)/src/([^/]+)(?:/(.*))?/?$", url)
    if bb_match:
        owner, repo, bb_branch, bb_subpath = bb_match.groups()
        clone_url = f"https://bitbucket.org/{owner}/{repo.removesuffix('.git')}.git"
        branch = branch or bb_branch
        subpath = bb_subpath or None
        return clone_url, branch, subpath

    return url, branch, None


def _find_project_dir(extract_dir: Path, target_subpath: str | None = None) -> Path:
    """Find the directory containing dbt_project.yml inside an extracted zip or cloned repository."""
    if target_subpath:
        sub_dir = extract_dir / target_subpath.strip().strip("/")
        if sub_dir.is_dir():
            if (sub_dir / "dbt_project.yml").is_file():
                return sub_dir
            candidates = list(sub_dir.rglob("dbt_project.yml"))
            if candidates:
                candidates.sort(key=lambda p: len(p.parts))
                return candidates[0].parent

    candidates = list(extract_dir.rglob("dbt_project.yml"))
    if not candidates:
        raise ValueError("Project directory does not contain 'dbt_project.yml'")
    # Sort by path length to choose topmost dbt_project.yml
    candidates.sort(key=lambda p: len(p.parts))
    return candidates[0].parent


def _container_input_path(path: Path, staging_dir: Path) -> str:
    resolved = path.resolve(strict=True)
    relative = resolved.relative_to(staging_dir.resolve(strict=True))
    return "/input/" + relative.as_posix()


def _container_workspace_path(path: Path, workspace: Path) -> str:
    resolved = path.resolve(strict=True)
    relative = resolved.relative_to(workspace.resolve(strict=True))
    return "/workspace/" + relative.as_posix()


def _docker_cli() -> str:
    docker = DOCKER_EXECUTABLE or shutil.which("docker")
    if not docker:
        raise RuntimeError("Docker is required to run projects. Install Docker Engine and start its daemon.")
    return docker


def _remove_session_container(session_id: str, reason: str) -> bool:
    session = RUN_SESSIONS.get(session_id)
    if not session or session.get("container_destroyed"):
        return True
    container_name = session.get("container_name")
    if container_name:
        try:
            result = subprocess.run(
                [_docker_cli(), "rm", "--force", str(container_name)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode and "No such container" not in (result.stderr + result.stdout):
                return False
        except (OSError, subprocess.TimeoutExpired, RuntimeError):
            return False

    session["container_destroyed"] = True
    session["status"] = "destroyed"
    session["destroy_reason"] = reason
    session["finished_at"] = datetime.now(timezone.utc).isoformat()
    for run_id in session.get("run_ids", []):
        run_info = RUNS_IN_FLIGHT.get(run_id)
        if run_info:
            run_info["container_destroyed"] = True
            if run_info.get("status") == "running":
                run_info["status"] = "cancelled"
                run_info["finished_at"] = session["finished_at"]
                run_info["error"] = f"Execution session ended: {reason}"
    for run_id in session.get("run_ids", []):
        SHELL_SESSIONS.pop(run_id, None)
    SHELL_SESSIONS.pop(session_id, None)
    return True


def _ensure_run_image() -> None:
    global RUN_IMAGE_BUILT
    docker = DOCKER_EXECUTABLE or shutil.which("docker")
    if not docker:
        raise RuntimeError("Docker is required to run projects. Install Docker Engine and start its daemon.")
    with RUN_IMAGE_BUILD_LOCK:
        if RUN_IMAGE_BUILT:
            return
        result = subprocess.run(
            [docker, "build", "-t", RUN_IMAGE, "-f", str(ROOT_DIR / "Dockerfile"), str(ROOT_DIR)],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if result.returncode:
            details = (result.stdout + result.stderr)[-5000:]
            raise RuntimeError(f"Could not build the dbt execution image: {details}")
        RUN_IMAGE_BUILT = True


def _replace_container_paths(value: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(value, str):
        for container_path, host_path in replacements:
            value = value.replace(container_path, host_path)
        return value
    if isinstance(value, list):
        return [_replace_container_paths(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_container_paths(item, replacements) for key, item in value.items()}
    return value


def _fail_container_run(run_id: str, message: str) -> None:
    finished_at = datetime.now(timezone.utc).isoformat()
    log_path = RUN_LOGS_DIR / f"run_{run_id}.log"
    report_path = RUN_LOGS_DIR / f"run_{run_id}.json"
    try:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\nContainer run failed: {message}\n")
        report_path.write_text(json.dumps({
            "run_id": run_id,
            "finished_at": finished_at,
            "overall_status": "failed",
            "failure_details": [message],
            "log_file": str(log_path),
            "structured_log_file": str(RUN_LOGS_DIR / f"run_{run_id}.events.jsonl"),
            "report_file": str(report_path),
        }, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    info = RUNS_IN_FLIGHT.get(run_id)
    if info is not None:
        info["status"] = "failed"
        info["finished_at"] = finished_at
        info["error"] = message


def _execute_run_worker(
    run_id: str,
    project_dir: Path,
    database_path: Path,
    data_dir: Path,
    verify_rerun: bool,
    compile_only: bool = False,
    execution_mode: str = "run",
    full_refresh: bool = False,
    select: str | None = None,
    run_config_path: Path | None = None,
    session_id: str | None = None,
) -> None:
    session_id = session_id or run_id
    session = RUN_SESSIONS.get(session_id)
    staging_dir = Path(session["staging_dir"]).resolve() if session else (UPLOADS_DIR / run_id).resolve()
    workspace = Path(session["workspace"]).resolve() if session else (CONTAINER_RUNS_DIR / session_id).resolve()
    run_workspace = workspace / "runs" / run_id
    container_name = str(session.get("container_name")) if session else f"dbt-session-{session_id}"
    info = RUNS_IN_FLIGHT.get(run_id)
    log_path = RUN_LOGS_DIR / f"run_{run_id}.log"
    event_path = RUN_LOGS_DIR / f"run_{run_id}.events.jsonl"
    report_path = RUN_LOGS_DIR / f"run_{run_id}.json"

    try:
        if session is not None and session.get("container_destroyed"):
            return
        if not project_dir.resolve(strict=True).is_relative_to(staging_dir):
            raise ValueError("Project path is outside this run's uploaded workspace")
        allowed_roots = (staging_dir, workspace)
        if not any(database_path.resolve(strict=True).is_relative_to(root) for root in allowed_roots):
            raise ValueError("Database path is outside this run session workspace")
        if data_dir and not any(data_dir.resolve(strict=True).is_relative_to(root) for root in allowed_roots):
            raise ValueError("Data path is outside this run session workspace")
        if run_config_path and not run_config_path.resolve(strict=True).is_relative_to(staging_dir):
            raise ValueError("Run configuration is outside this run session workspace")
        if os.getuid() == 0:
            raise RuntimeError("Run the web server as an unprivileged user so run containers do not run as root.")

        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "home").mkdir(exist_ok=True)
        (workspace / "runs").mkdir(exist_ok=True)
        run_workspace.mkdir(parents=True, exist_ok=False)
        container_log_dir = workspace / "logs"
        container_log_dir.mkdir(exist_ok=True)
        container_log_files = {
            log_path: container_log_dir / log_path.name,
            event_path: container_log_dir / event_path.name,
            report_path: container_log_dir / report_path.name,
        }
        for host_path, isolated_path in container_log_files.items():
            host_path.parent.mkdir(parents=True, exist_ok=True)
            if host_path.is_symlink() or host_path.exists():
                raise FileExistsError(f"Run log path already exists: {host_path}")
            isolated_path.touch()
            host_path.symlink_to(isolated_path)

        if info is not None:
            info["container_name"] = container_name
            info["container_workspace"] = str(workspace)
            info["run_workspace"] = str(run_workspace)
            info["session_id"] = session_id

        _ensure_run_image()
        docker = _docker_cli()
        project_input = _container_input_path(project_dir, staging_dir)
        database_input = (
            _container_input_path(database_path, staging_dir)
            if database_path.resolve().is_relative_to(staging_dir)
            else _container_workspace_path(database_path, workspace)
        )
        data_input = None
        if data_dir:
            data_input = (
                _container_input_path(data_dir, staging_dir)
                if data_dir.resolve().is_relative_to(staging_dir)
                else _container_workspace_path(data_dir, workspace)
            )
        run_config_input = _container_input_path(run_config_path, staging_dir) if run_config_path else None

        inspect = subprocess.run(
            [docker, "inspect", "--format", "{{.State.Running}}", container_name],
            capture_output=True, text=True, timeout=15,
        )
        if inspect.returncode == 0:
            if inspect.stdout.strip().lower() != "true":
                started = subprocess.run([docker, "start", container_name], capture_output=True, text=True, timeout=30)
                if started.returncode:
                    raise RuntimeError((started.stderr or started.stdout or "Could not restart the session container.").strip())
        else:
            docker_args = [
                docker, "run", "--detach", "--init", "--name", container_name,
                "--label", "dbt-runner.managed=true",
                "--label", f"dbt-runner.session-id={session_id}",
                "--label", f"dbt-runner.run-id={run_id}",
                "--network=none", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--pids-limit=256",
                "--memory=2g", "--cpus=2", "--ulimit", "nofile=1024:1024",
                "--ulimit", "fsize=2147483648:2147483648",
                "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m",
                "--mount", f"type=bind,src={staging_dir},dst=/input,readonly",
                "--mount", f"type=bind,src={workspace},dst=/workspace",
                "--mount", f"type=bind,src={container_log_dir},dst=/app/run_logs",
                "--workdir", "/app",
                "--user", f"{os.getuid()}:{os.getgid()}",
                "--env", "HOME=/workspace/home",
                "--env", "DBT_SEND_ANONYMOUS_USAGE_STATS=false",
                "--env", "DBT_VERSION_CHECK=false",
                RUN_IMAGE, "/bin/sleep", "infinity",
            ]
            launched = subprocess.run(docker_args, capture_output=True, text=True, timeout=120)
            if launched.returncode:
                raise RuntimeError((launched.stderr or launched.stdout or "Docker did not start the session container.").strip())
            if info is not None:
                info["container_id"] = launched.stdout.strip()
            if session is not None:
                session["container_id"] = launched.stdout.strip()

        if session is not None and session.get("container_destroyed"):
            subprocess.run([docker, "rm", "--force", container_name], capture_output=True, timeout=15)
            return

        worker_args = [
            docker, "exec", "--detach", "--workdir", "/app",
            "--env", "HOME=/workspace/home",
            "--env", "DBT_SEND_ANONYMOUS_USAGE_STATS=false",
            "--env", "DBT_VERSION_CHECK=false",
            container_name,
            "python", "/app/server/container_worker.py",
            "--run-id", run_id,
            "--project-dir", project_input,
            "--database", database_input,
            "--sandbox-dir", f"/workspace/runs/{run_id}/runtime",
            "--execution-mode", "compile" if compile_only or execution_mode == "compile" else "run",
        ]
        if run_config_input:
            worker_args.extend(["--run-config", run_config_input])
        if data_input:
            worker_args.extend(["--data-dir", data_input])
        if verify_rerun:
            worker_args.append("--verify-rerun")
        if compile_only:
            worker_args.append("--compile-only")
        if full_refresh:
            worker_args.append("--full-refresh")
        if select:
            worker_args.extend(["--select", select])

        launched = subprocess.run(worker_args, capture_output=True, text=True, timeout=120)
        if launched.returncode:
            raise RuntimeError((launched.stderr or launched.stdout or "Docker could not start the run worker.").strip())
        if info is not None:
            info["container_name"] = container_name
        if session is not None:
            session["container_name"] = container_name
            session["last_seen"] = time.monotonic()
            session["status"] = "running"
            session["active_run_id"] = run_id

        deadline = time.monotonic() + 8 * 60 * 60
        next_inspect = 0.0
        while time.monotonic() < deadline:
            try:
                container_report = json.loads(report_path.read_text(encoding="utf-8"))
                if container_report.get("finished_at") and container_report.get("overall_status") in {"passed", "failed", "needs_configuration"}:
                    if session is not None and session.get("container_destroyed"):
                        return
                    replacements = [
                        ("/app/run_logs", str(RUN_LOGS_DIR)),
                        ("/workspace", str(workspace)),
                        ("/input", str(staging_dir)),
                    ]
                    normalized = _replace_container_paths(container_report, replacements)
                    normalized["session_id"] = session_id
                    report_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                    if info is not None:
                        info["status"] = normalized["overall_status"]
                        info["finished_at"] = normalized.get("finished_at", datetime.now(timezone.utc).isoformat())
                        info["report"] = normalized
                        info["database_location"] = normalized.get("ducklake_metadata_location", info.get("database_location"))
                        info["data_location"] = normalized.get("data_location") or None
                        info["session_id"] = session_id
                    if session is not None:
                        session["last_seen"] = time.monotonic()
                        session["status"] = "idle"
                        session["active_run_id"] = None
                        session["latest_run_id"] = run_id
                    return
            except (OSError, json.JSONDecodeError):
                pass

            now = time.monotonic()
            if now >= next_inspect:
                next_inspect = now + 5
                inspect = subprocess.run(
                    [docker, "inspect", "--format", "{{.State.Running}}", container_name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if inspect.returncode or inspect.stdout.strip().lower() != "true":
                    logs = subprocess.run([docker, "logs", container_name], capture_output=True, text=True, timeout=10)
                    detail = (logs.stdout + logs.stderr)[-4000:]
                    raise RuntimeError(f"The run container exited before writing its report. {detail}")
            time.sleep(0.25)
        raise TimeoutError("The container run exceeded its 8-hour limit")
    except Exception as exc:
        if session is not None and session.get("status") == "destroyed":
            return
        _fail_container_run(run_id, str(exc))
        if session is not None:
            session["status"] = "idle"
            session["active_run_id"] = None


def _cleanup_run_containers() -> None:
    docker = DOCKER_EXECUTABLE or shutil.which("docker")
    if not docker:
        return
    container_names = {
        str(session.get("container_name")) for session in RUN_SESSIONS.values()
        if session.get("container_name")
    }
    container_names.update(
        str(info.get("container_name")) for info in RUNS_IN_FLIGHT.values()
        if info.get("container_name")
    )
    for container_name in container_names:
        if container_name:
            try:
                subprocess.run([docker, "rm", "--force", container_name], capture_output=True, timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                pass


atexit.register(_cleanup_run_containers)


async def _expire_idle_sessions() -> None:
    while True:
        now = time.monotonic()
        for session_id, session in list(RUN_SESSIONS.items()):
            if session.get("container_destroyed"):
                continue
            if now - float(session.get("last_seen", now)) >= SESSION_IDLE_TTL_SECONDS:
                _remove_session_container(session_id, "browser session expired")
        await asyncio.sleep(15)


@app.on_event("startup")
async def start_session_reaper() -> None:
    asyncio.create_task(_expire_idle_sessions())


@app.post("/api/run")
async def start_run(
    background_tasks: BackgroundTasks,
    project_zip: UploadFile | None = File(None, description="Zip file containing dbt project"),
    git_url: str | None = Form(None, description="Git repository URL containing dbt project"),
    git_branch: str | None = Form(None, description="Git branch, tag or commit"),
    raw_data_files: list[UploadFile] = File(default=[], description="Raw data files (.csv, .parquet, .json, .zip)"),
    verify_rerun: bool = Form(True),
    compile_only: bool = Form(False),
    execution_mode: str = Form("run", description="Execution mode: 'run' (dbt run), 'compile' (dbt compile)"),
    full_refresh: bool = Form(False, description="Whether to run with --full-refresh"),
    select: str | None = Form(None, description="Model selection expression (--select)"),
    exclude: str | None = Form(None, description="Model exclusion expression (--exclude)"),
    vars_json: str | None = Form(None, description="dbt vars as a JSON object"),
    target_database: str | None = Form(None),
    target_schema: str | None = Form(None),
    adapter_type: str | None = Form(None),
    run_tests: bool = Form(True),
    file_mappings_json: str | None = Form(None),
    approved_sql_scripts_json: str | None = Form(None),
    sql_target_compatibility: str | None = Form(None),
) -> dict[str, Any]:
    run_id = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    shell_token = secrets.token_urlsafe(32)
    session_token = secrets.token_urlsafe(32)
    staging_dir = UPLOADS_DIR / run_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Obtain dbt project either via zip extract or git clone
        proj_extract_dir = staging_dir / "project"

        has_zip = project_zip is not None and bool(project_zip.filename)
        has_git = bool(git_url and git_url.strip())

        if not has_zip and not has_git:
            raise ValueError("Please provide either a dbt project .zip file or a Git repository URL.")

        clone_url: str | None = None
        branch: str | None = None
        subpath: str | None = None

        if has_zip:
            proj_zip_path = staging_dir / "project_upload.zip"
            with proj_zip_path.open("wb") as f:
                shutil.copyfileobj(project_zip.file, f)
            _extract_zip(proj_zip_path, proj_extract_dir)
            project_dir = _find_project_dir(proj_extract_dir)
            display_name = project_dir.name
        else:
            clone_url, branch, subpath = normalize_git_url(git_url, git_branch)
            clone_cmd = ["git", "clone", "--depth", "1"]
            if branch:
                clone_cmd.extend(["-b", branch])
            clone_cmd.extend([clone_url, str(proj_extract_dir)])

            try:
                result = subprocess.run(
                    clone_cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode != 0:
                    # If cloning with specific branch failed, attempt fallback clone without branch flag
                    if branch:
                        fallback_cmd = ["git", "clone", "--depth", "1", clone_url, str(proj_extract_dir)]
                        fallback_res = subprocess.run(fallback_cmd, capture_output=True, text=True, timeout=60)
                        if fallback_res.returncode != 0:
                            err_msg = fallback_res.stderr.strip() or fallback_res.stdout.strip()
                            raise ValueError(f"Git clone failed: {err_msg}")
                    else:
                        err_msg = result.stderr.strip() or result.stdout.strip()
                        raise ValueError(f"Git clone failed: {err_msg}")
            except subprocess.TimeoutExpired:
                raise ValueError("Git clone timed out after 60 seconds.")
            except FileNotFoundError:
                raise ValueError("Git command not found on host system.")

            project_dir = _find_project_dir(proj_extract_dir, target_subpath=subpath)
            repo_name = clone_url.rstrip("/").split("/")[-1].removesuffix(".git")
            if subpath:
                display_name = f"{repo_name}/{subpath}"
            elif project_dir != proj_extract_dir:
                try:
                    rel = project_dir.relative_to(proj_extract_dir)
                    display_name = f"{repo_name}/{rel}"
                except ValueError:
                    display_name = f"{repo_name} ({project_dir.name})"
            else:
                display_name = repo_name

        ingested_tables: list[dict[str, Any]] = []

        # Collect all raw data uploads
        all_raw_uploads = [u for u in raw_data_files if u and u.filename]

        # Candidate uploads remain separate from dbt seeds and are never loaded implicitly.
        if all_raw_uploads:
            raw_data_staging = project_dir / "candidate_inputs"
            raw_data_staging.mkdir(parents=True, exist_ok=True)

            for upload_index, upload in enumerate(all_raw_uploads):
                filename = upload.filename or "data.csv"
                safe_filename = Path(filename.replace("\\", "/")).name
                if safe_filename in {"", ".", ".."}:
                    raise ValueError("Uploaded data file has an invalid filename.")
                is_zip = safe_filename.lower().endswith(".zip")

                if is_zip:
                    temp_raw_zip = staging_dir / f"raw_zip_{upload_index}_{safe_filename}"
                    with temp_raw_zip.open("wb") as f:
                        shutil.copyfileobj(upload.file, f)
                    _extract_zip(temp_raw_zip, raw_data_staging)
                else:
                    dest_file = raw_data_staging / safe_filename
                    with dest_file.open("wb") as f:
                        shutil.copyfileobj(upload.file, f)

        db_dest = staging_dir / "execution.duckdb"
        import duckdb
        init_con = duckdb.connect(str(db_dest))
        init_con.close()
        data_dir = None

    except ValueError as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to process uploaded data: {exc}")

    clean_select = select.strip() if select and select.strip() else None
    effective_compile = compile_only or execution_mode == "compile"
    effective_mode = "compile" if effective_compile else "run"
    try:
        file_mappings = json.loads(file_mappings_json) if file_mappings_json else {}
        approved_sql_scripts = json.loads(approved_sql_scripts_json) if approved_sql_scripts_json else []
        vars_config = json.loads(vars_json) if vars_json else {}
        if not isinstance(file_mappings, dict) or not isinstance(approved_sql_scripts, list) or not isinstance(vars_config, dict):
            raise ValueError("File mappings and dbt vars must be objects; approved SQL scripts must be a list.")
    except (json.JSONDecodeError, ValueError) as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Invalid source preparation configuration: {exc}")
    run_config_path = staging_dir / "run_config.json"
    run_config = {
        "run_logs_dir": "run_logs", "target_database": target_database,
        "target_schema": target_schema, "adapter_type": adapter_type,
        "run_tests": run_tests, "file_mappings": file_mappings,
        "approved_sql_scripts": approved_sql_scripts,
        "sql_target_compatibility": sql_target_compatibility,
        "exclude": exclude,
        "vars": vars_config,
    }
    run_config_path.write_text(json.dumps(run_config, indent=2) + "\n", encoding="utf-8")

    RUNS_IN_FLIGHT[run_id] = {
        "run_id": run_id,
        "shell_token": shell_token,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": "",
        "project_name": display_name,
        "project_dir": str(project_dir),
        "source_type": "git" if has_git else "zip",
        "git_url": clone_url if has_git else None,
        "git_branch": branch if (has_git and branch) else None,
        "database_location": str(db_dest),
        "data_location": str(data_dir),
        "verify_rerun": verify_rerun,
        "staging_dir": str(staging_dir),
        "ingested_tables": ingested_tables,
        "log_file": str(RUN_LOGS_DIR / f"run_{run_id}.log"),
        "structured_log_file": str(RUN_LOGS_DIR / f"run_{run_id}.events.jsonl"),
        "report_file": str(RUN_LOGS_DIR / f"run_{run_id}.json"),
        "compile_only": effective_compile,
        "execution_mode": effective_mode,
        "full_refresh": full_refresh,
        "select": clean_select,
        "error": None,
        "session_id": run_id,
        "session_token": session_token,
        "container_name": f"dbt-session-{run_id}",
        "container_workspace": str(CONTAINER_RUNS_DIR / run_id),
        "container_project_dir": f"/workspace/runs/{run_id}/runtime/project",
        "container_input_project": "/input/" + project_dir.resolve().relative_to(staging_dir.resolve()).as_posix(),
        "database_type": "duckdb",
        "run_config_path": str(run_config_path),
    }

    RUN_SESSIONS[run_id] = {
        "session_id": run_id,
        "session_token": session_token,
        "staging_dir": str(staging_dir),
        "project_dir": str(project_dir),
        "workspace": str(CONTAINER_RUNS_DIR / run_id),
        "container_name": f"dbt-session-{run_id}",
        "status": "starting",
        "container_destroyed": False,
        "last_seen": time.monotonic(),
        "active_run_id": run_id,
        "latest_run_id": run_id,
        "run_ids": [run_id],
    }

    background_tasks.add_task(
        _execute_run_worker,
        run_id,
        project_dir,
        db_dest,
        data_dir,
        verify_rerun,
        effective_compile,
        execution_mode,
        full_refresh,
        clean_select,
        run_config_path,
        run_id,
    )

    return {
        "run_id": run_id,
        "session_id": run_id,
        "session_token": session_token,
        "shell_token": shell_token,
        "status": "running",
        "started_at": RUNS_IN_FLIGHT[run_id]["started_at"],
        "project_name": display_name,
        "source_type": "git" if has_git else "zip",
        "compile_only": effective_compile,
        "execution_mode": execution_mode,
        "full_refresh": full_refresh,
        "select": clean_select,
    }



@app.get("/api/runs")
def list_runs() -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    # In flight runs first
    for r_id, info in RUNS_IN_FLIGHT.items():
        seen_ids.add(r_id)
        runs.append({
            "run_id": r_id,
            "status": info.get("status", "running"),
            "started_at": info.get("started_at", ""),
            "finished_at": info.get("finished_at", ""),
            "project_name": Path(info.get("project_dir", "dbt_project")).name,
            "database_type": info.get("database_type", "unknown"),
            "execution_mode": info.get("execution_mode", "run"),
            "full_refresh": info.get("full_refresh", False),
            "select": info.get("select"),
            "container_destroyed": info.get("container_destroyed", False),
        })

    # Saved reports from disk
    if RUN_LOGS_DIR.is_dir():
        for report_file in sorted(RUN_LOGS_DIR.glob("run_*.json"), reverse=True):
            r_id = report_file.stem.replace("run_", "")
            if r_id in seen_ids:
                continue
            seen_ids.add(r_id)
            try:
                data = json.loads(report_file.read_text(encoding="utf-8"))
                runs.append({
                    "run_id": data.get("run_id", r_id),
                    "status": data.get("overall_status", "unknown"),
                    "started_at": data.get("started_at", ""),
                    "finished_at": data.get("finished_at", ""),
                    "project_name": Path(data.get("project_dir", "dbt_project")).name,
                    "database_type": data.get("database_type", "unknown"),
                    "steps_count": len(data.get("steps", [])),
                    "models_count": len(data.get("model_executions", [])),
                    "execution_mode": data.get("execution_mode", "run"),
                    "full_refresh": data.get("full_refresh", False),
                    "select": data.get("select"),
                })
            except Exception:
                pass

    return runs


@app.websocket("/api/runs/{run_id}/shell")
async def project_shell(websocket: WebSocket, run_id: str) -> None:
    """Attach a shell to the same per-run container that executed dbt."""
    run_info = RUNS_IN_FLIGHT.get(run_id)
    expected_token = str((run_info or {}).get("shell_token") or "")
    protocols = [value.strip() for value in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    supplied_token = next((value for value in protocols if value != "dbt-shell"), "")
    if not expected_token or not secrets.compare_digest(supplied_token, expected_token):
        await websocket.close(code=4403, reason="Console access token is invalid or expired")
        return

    await websocket.accept(subprotocol="dbt-shell")
    try:
        docker = DOCKER_EXECUTABLE or shutil.which("docker")
        if not docker:
            raise RuntimeError("Docker is required for this run's interactive console.")

        session_id = str(run_info.get("session_id") or run_id)
        async with SHELL_SESSION_LOCK:
            session = SHELL_SESSIONS.get(session_id)
            if session is None:
                session = {"lock": asyncio.Lock()}
                SHELL_SESSIONS[session_id] = session

        if session["lock"].locked():
            await websocket.send_text("This run already has an active shell connection.\r\n")
            await websocket.close(code=4409, reason="Shell is already connected")
            return

        async with session["lock"]:
            import pty

            container_name = run_info.get("container_name")
            if not container_name:
                raise RuntimeError("The run container has not been assigned yet.")

            await websocket.send_text("Waiting for the run container…\r\n")
            container_ready = False
            for _ in range(2400):
                if run_info.get("status") == "failed":
                    raise RuntimeError(run_info.get("error") or "Run container startup failed.")
                inspect = await asyncio.create_subprocess_exec(
                    docker, "inspect", "--format", "{{.State.Running}}", container_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                output, _ = await inspect.communicate()
                if inspect.returncode == 0 and output.decode().strip().lower() == "true":
                    container_ready = True
                    break
                await asyncio.sleep(0.25)
            if not container_ready:
                raise RuntimeError("The run container did not start. Check the run log for Docker errors.")

            host_workspace = Path(run_info["container_workspace"])
            run_workspace = Path(run_info.get("run_workspace") or (host_workspace / "runs" / run_id))
            expected_project = run_workspace / "runtime" / "project"
            container_workdir = str(run_info.get("container_project_dir") or f"/workspace/runs/{run_id}/runtime/project")
            for _ in range(600):
                if expected_project.is_dir() or run_info.get("status") in {"passed", "failed"}:
                    break
                await asyncio.sleep(0.1)
            if not expected_project.is_dir():
                container_workdir = run_info.get("container_input_project", "/input")

            master_fd, slave_fd = pty.openpty()
            docker_args = [
                docker, "exec", "--interactive", "--tty",
                "--workdir", container_workdir,
                "--env", "HOME=/workspace/home",
                "--env", f"DBT_PROFILES_DIR=/workspace/runs/{run_id}/runtime/profiles",
                "--env", f"DBT_TARGET_PATH=/workspace/runs/{run_id}/runtime/target",
                "--env", "DBT_SEND_ANONYMOUS_USAGE_STATS=false",
                "--env", "DBT_VERSION_CHECK=false",
                "--env", "DUCKDB_EXTENSION_DIRECTORY=/opt/duckdb/extensions",
                container_name,
                "/bin/bash", "--noprofile", "--norc", "-i",
            ]
            process = await asyncio.create_subprocess_exec(
                *docker_args,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
            )
            os.close(slave_fd)
            await websocket.send_text(f"Connected to run container: {container_name}\r\n")

            async def forward_terminal_output() -> None:
                bytes_sent = 0
                loop = asyncio.get_running_loop()
                while True:
                    readable = loop.create_future()

                    def notify_readable() -> None:
                        if not readable.done():
                            readable.set_result(None)

                    loop.add_reader(master_fd, notify_readable)
                    try:
                        await readable
                    except OSError:
                        return
                    finally:
                        loop.remove_reader(master_fd)
                    try:
                        data = os.read(master_fd, 4096)
                    except OSError:
                        return
                    if not data:
                        return
                    bytes_sent += len(data)
                    if bytes_sent > 5_000_000:
                        await websocket.send_text("\r\nShell output limit reached; reconnect to start a new session.\r\n")
                        return
                    try:
                        await websocket.send_text(data.decode("utf-8", errors="replace"))
                    except (WebSocketDisconnect, RuntimeError):
                        return

            async def forward_terminal_input() -> None:
                try:
                    while True:
                        text = await websocket.receive_text()
                        if len(text) > 16_384:
                            await websocket.send_text("\r\nInput limit exceeded (16 KB per message).\r\n")
                            continue
                        os.write(master_fd, text.encode("utf-8"))
                except WebSocketDisconnect:
                    return

            output_task = asyncio.create_task(forward_terminal_output())
            input_task = asyncio.create_task(forward_terminal_input())
            try:
                done, pending = await asyncio.wait(
                    {output_task, input_task}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                for task in done:
                    task.result()
            finally:
                if process.returncode is None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(process.wait(), timeout=3)
                    except asyncio.TimeoutError:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        await process.wait()
                os.close(master_fd)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await websocket.send_text(f"\r\nShell unavailable: {exc}\r\n")
            await websocket.close(code=1011)
        except Exception:
            pass


@app.post("/api/runs/{run_id}/destroy-container")
def destroy_run_container(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """End the run's project session while preserving saved reports and sandboxes."""
    run_info = RUNS_IN_FLIGHT.get(run_id)
    expected_token = run_info.get("shell_token", "") if run_info else ""
    supplied_token = str(payload.get("shell_token") or "")
    if not expected_token or not secrets.compare_digest(supplied_token, expected_token):
        raise HTTPException(status_code=403, detail="Run access token is invalid or expired")
    session_id = str(run_info.get("session_id") or run_id)
    if not _remove_session_container(session_id, "container removed by user"):
        raise HTTPException(status_code=502, detail="Could not remove the project session container")
    return {"run_id": run_id, "session_id": session_id, "container_destroyed": True, "workspace_preserved": True}


@app.post("/api/sessions/{session_id}/heartbeat")
def heartbeat_project_session(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = RUN_SESSIONS.get(session_id)
    supplied = str(payload.get("session_token") or "")
    expected = str((session or {}).get("session_token") or "")
    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Project session token is invalid or expired")
    if session.get("container_destroyed"):
        raise HTTPException(status_code=410, detail="Project session has ended")
    session["last_seen"] = time.monotonic()
    return {"session_id": session_id, "status": session.get("status", "idle")}


@app.post("/api/sessions/{session_id}/leave")
def leave_project_session(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = RUN_SESSIONS.get(session_id)
    supplied = str(payload.get("session_token") or "")
    expected = str((session or {}).get("session_token") or "")
    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Project session token is invalid or expired")
    if not _remove_session_container(session_id, "user left the project page"):
        raise HTTPException(status_code=502, detail="Could not remove the project session container")
    return {"session_id": session_id, "container_destroyed": True}


@app.get("/api/containers")
def list_application_containers() -> list[dict[str, str]]:
    """List containers marked as managed by this application, including stopped ones."""
    docker = DOCKER_EXECUTABLE or shutil.which("docker")
    if not docker:
        raise HTTPException(status_code=503, detail="Docker is unavailable")
    try:
        result = subprocess.run(
            [docker, "ps", "--all", "--filter", "label=dbt-runner.managed=true", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=503, detail=f"Could not list Docker containers: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "Docker could not list containers.").strip()
        raise HTTPException(status_code=503, detail=detail)

    containers: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        try:
            docker_row = json.loads(line)
        except json.JSONDecodeError:
            continue
        labels: dict[str, str] = {}
        for label in str(docker_row.get("Labels") or "").split(","):
            key, separator, value = label.partition("=")
            if separator:
                labels[key] = value
        if labels.get("dbt-runner.managed") != "true":
            continue
        session_id = labels.get("dbt-runner.session-id") or labels.get("dbt-runner.run-id", "")
        session = RUN_SESSIONS.get(session_id, {})
        containers.append({
            "container_id": str(docker_row.get("ID") or ""),
            "name": str(docker_row.get("Names") or ""),
            "image": str(docker_row.get("Image") or ""),
            "status": str(docker_row.get("Status") or "unknown"),
            "created": str(docker_row.get("CreatedAt") or ""),
            "run_id": str(session.get("latest_run_id") or labels.get("dbt-runner.run-id", "")),
            "session_id": session_id,
        })
    return containers


@app.delete("/api/containers/{container_id}")
def destroy_application_container(container_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Remove a container only after verifying the application-managed label."""
    if not re.fullmatch(r"[0-9a-fA-F]{12,64}", container_id):
        raise HTTPException(status_code=400, detail="Invalid Docker container ID")
    docker = DOCKER_EXECUTABLE or shutil.which("docker")
    if not docker:
        raise HTTPException(status_code=503, detail="Docker is unavailable")
    label_format = '{{ index .Config.Labels "dbt-runner.managed" }}|{{ index .Config.Labels "dbt-runner.run-id" }}|{{ index .Config.Labels "dbt-runner.session-id" }}'
    try:
        inspected = subprocess.run(
            [docker, "inspect", "--format", label_format, container_id],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=503, detail=f"Could not inspect Docker container: {exc}") from exc
    if inspected.returncode:
        raise HTTPException(status_code=404, detail="Docker container was not found")
    parts = inspected.stdout.strip().split("|", 2)
    managed_label = parts[0] if parts else ""
    run_id = parts[1] if len(parts) > 1 else ""
    session_id = parts[2] if len(parts) > 2 else run_id
    if session_id in {"", "<no value>"}:
        session_id = run_id
    if managed_label != "true":
        raise HTTPException(status_code=403, detail="This container is not managed by dbt Runner")
    session = RUN_SESSIONS.get(session_id)
    expected_token = str((session or {}).get("session_token") or "")
    supplied_token = str(payload.get("session_token") or "")
    if not expected_token or not secrets.compare_digest(supplied_token, expected_token):
        raise HTTPException(status_code=403, detail="Project session token is invalid or unavailable")
    if not _remove_session_container(session_id, "container removed by user"):
        raise HTTPException(status_code=502, detail="Could not remove the project session container")
    return {"container_id": container_id, "run_id": run_id, "session_id": session_id, "container_destroyed": True}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    report_file = RUN_LOGS_DIR / f"run_{run_id}.json"
    if report_file.is_file():
        try:
            data = json.loads(report_file.read_text(encoding="utf-8"))
            run_info = RUNS_IN_FLIGHT.get(run_id)
            if run_info and run_info.get("ingested_tables"):
                data["ingested_tables"] = run_info["ingested_tables"]
            if run_info:
                data["container_destroyed"] = run_info.get("container_destroyed", False)
                data["session_id"] = run_info.get("session_id")
                if run_info.get("status") == "cancelled":
                    data["overall_status"] = "cancelled"
                    data["finished_at"] = run_info.get("finished_at", "")
                    data["failure_details"] = [run_info.get("error") or "Project session ended."]
            return data
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not read report file: {exc}")

    if run_id in RUNS_IN_FLIGHT:
        info = RUNS_IN_FLIGHT[run_id]
        return {
            "run_id": run_id,
            "session_id": info.get("session_id"),
            "overall_status": info.get("status", "running"),
            "started_at": info.get("started_at", ""),
            "finished_at": info.get("finished_at", ""),
            "project_dir": info.get("project_dir", ""),
            "ducklake_metadata_location": info.get("database_location", ""),
            "data_location": info.get("data_location", ""),
            "ingested_tables": info.get("ingested_tables", []),
            "steps": [],
            "failure_details": [info["error"]] if info.get("error") else [],
        }

    raise HTTPException(status_code=404, detail=f"Run {run_id} not found")


@app.get("/api/runs/{run_id}/logs")
def get_run_logs(run_id: str) -> dict[str, Any]:
    log_file = RUN_LOGS_DIR / f"run_{run_id}.log"
    if not log_file.is_file():
        return {"run_id": run_id, "logs": ""}
    return {"run_id": run_id, "logs": log_file.read_text(encoding="utf-8", errors="replace")}


@app.get("/api/runs/{run_id}/preview")
def preview_table_data(
    run_id: str,
    table: str,
    schema: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Fetch sample rows for a table from the run's database state or report."""
    report_file = RUN_LOGS_DIR / f"run_{run_id}.json"
    run_info = RUNS_IN_FLIGHT.get(run_id, {})
    report_data: dict[str, Any] = {}
    if report_file.is_file():
        try:
            report_data = json.loads(report_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    clean_table = table.split(".")[-1]
    if not schema or not schema.strip():
        raise HTTPException(status_code=400, detail="A schema must be specified for relation preview.")
    clean_schema = schema.split(".")[-1]

    db_path_str = run_info.get("database_location") or report_data.get("ducklake_metadata_location")
    data_dir_str = run_info.get("data_location") or report_data.get("data_location")
    inferred_type = "ducklake" if db_path_str and Path(db_path_str).suffix.casefold() == ".ducklake" else "duckdb"
    db_type = report_data.get("database_type") or inferred_type

    # 1. Attempt live query if database file exists on disk
    if db_path_str and Path(db_path_str).exists():
        try:
            import duckdb
            db_path = Path(db_path_str)
            data_dir = Path(data_dir_str) if data_dir_str else None

            conn = duckdb.connect(":memory:")
            resolved_target = report_data.get("effective_target_config") or {}
            cat_name = str(resolved_target.get("database") or db_path.stem)
            quote_identifier = lambda value: '"' + str(value).replace('"', '""') + '"'
            if db_type == "ducklake" and data_dir and data_dir.is_dir():
                conn.execute("INSTALL ducklake; LOAD ducklake;")
                escaped_db = str(db_path).replace("'", "''")
                escaped_data = str(data_dir).replace("'", "''")
                conn.execute(
                    f"ATTACH 'ducklake:{escaped_db}' AS {quote_identifier(cat_name)} (DATA_PATH '{escaped_data}', OVERRIDE_DATA_PATH TRUE, READ_ONLY TRUE)"
                )
            else:
                escaped_db = str(db_path).replace("'", "''")
                conn.execute(f"ATTACH '{escaped_db}' AS {quote_identifier(cat_name)} (READ_ONLY)")

            relation = f"{quote_identifier(cat_name)}.{quote_identifier(clean_schema)}.{quote_identifier(clean_table)}"
            cnt_row = conn.execute(f"SELECT COUNT(*) FROM {relation}").fetchone()
            row_count = cnt_row[0] if cnt_row else 0

            cur = conn.execute(f"SELECT * FROM {relation} LIMIT {max(1, min(limit, 500))}")
            columns = [d[0] for d in cur.description] if cur.description else []
            raw_rows = cur.fetchall()
            rows = []
            for r in raw_rows:
                row_dict = {}
                for col_name, val in zip(columns, r):
                    if val is None:
                        row_dict[col_name] = None
                    elif isinstance(val, (int, float, bool, str)):
                        row_dict[col_name] = val
                    else:
                        row_dict[col_name] = str(val)
                rows.append(row_dict)
            conn.close()

            return {
                "status": "success",
                "run_id": run_id,
                "database": cat_name,
                "schema": clean_schema,
                "table": clean_table,
                "row_count": row_count,
                "columns": columns,
                "rows": rows,
                "refreshed_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception:
            pass

    # 2. Fallback to cached sample rows in report_data
    if report_data:
        actual_objects = report_data.get("object_validation", {}).get("actual_objects", [])
        for obj in actual_objects:
            obj_name = obj.get("name")
            obj_sch = obj.get("schema")
            if obj_name == clean_table and (not schema or obj_sch == clean_schema):
                return {
                    "status": "success",
                    "run_id": run_id,
                    "database": obj.get("database", ""),
                    "schema": obj_sch,
                    "table": obj_name,
                    "row_count": obj.get("row_count", len(obj.get("sample_rows", []))),
                    "columns": obj.get("sample_columns") or [c.get("name") for c in obj.get("columns", [])],
                    "rows": obj.get("sample_rows", []),
                    "refreshed_at": datetime.now(timezone.utc).isoformat(),
                }

    return {
        "status": "no_data",
        "run_id": run_id,
        "schema": clean_schema,
        "table": clean_table,
        "row_count": 0,
        "columns": [],
        "rows": [],
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "message": "No sample data available for this relation.",
    }


def _launch_rerun(
    run_id: str,
    full_refresh: bool,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prev_run = RUNS_IN_FLIGHT.get(run_id)
    report_file = RUN_LOGS_DIR / f"run_{run_id}.json"
    rep_data = None
    if report_file.is_file():
        try:
            rep_data = json.loads(report_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    if not prev_run and not rep_data:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")

    session_id = str((prev_run or {}).get("session_id") or (rep_data or {}).get("session_id") or run_id)
    session = RUN_SESSIONS.get(session_id)
    if not session or session.get("container_destroyed"):
        raise HTTPException(status_code=410, detail="This project session has ended. Start a new project run.")
    if session.get("status") == "running":
        raise HTTPException(status_code=409, detail="This project already has a run in progress.")

    staging_dir = Path(session["staging_dir"])
    project_dir_str = str(session.get("project_dir") or (prev_run or {}).get("project_dir") or "")
    if not project_dir_str or not Path(project_dir_str).is_dir():
        raise HTTPException(status_code=400, detail=f"Project directory for session {session_id} not found.")
    project_dir = Path(project_dir_str)
    old_db_str = (prev_run.get("database_location") if prev_run else None) or (rep_data.get("ducklake_metadata_location") if rep_data else "")
    old_data_str = (prev_run.get("data_location") if prev_run else None) or (rep_data.get("data_location") if rep_data else "")
    old_db = Path(old_db_str) if old_db_str else None
    old_data = Path(old_data_str) if old_data_str else None
    if not old_db or not old_db.is_file():
        initial_database = staging_dir / "execution.duckdb"
        if initial_database.is_file():
            old_db = initial_database
    if old_data and not old_data.is_dir():
        old_data = None

    new_run_id = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    shell_token = secrets.token_urlsafe(32)
    previous_config_path = Path(prev_run.get("run_config_path")) if prev_run and prev_run.get("run_config_path") else (staging_dir / "run_config.json" if staging_dir else None)
    run_config: dict[str, Any] = {}
    if previous_config_path and previous_config_path.is_file():
        try:
            loaded_config = json.loads(previous_config_path.read_text(encoding="utf-8"))
            if isinstance(loaded_config, dict):
                run_config = loaded_config
        except (OSError, json.JSONDecodeError):
            pass
    for key in ("target_database", "target_schema", "adapter_type", "run_tests", "file_mappings", "approved_sql_scripts", "sql_target_compatibility", "exclude", "vars"):
        if payload is not None and key in payload:
            run_config[key] = payload[key]
    run_config_dir = staging_dir / "run_configs"
    run_config_dir.mkdir(parents=True, exist_ok=True)
    run_config_path = run_config_dir / f"{new_run_id}.json"
    run_config_path.write_text(json.dumps(run_config, indent=2) + "\n", encoding="utf-8")

    select_val = None
    if payload and "select" in payload and payload["select"]:
        select_val = str(payload["select"]).strip() or None
    elif prev_run and prev_run.get("select"):
        select_val = prev_run.get("select")
    elif rep_data and rep_data.get("select"):
        select_val = rep_data.get("select")

    # Determine execution mode from payload or inherit from previous run
    prev_mode = None
    if prev_run:
        prev_mode = prev_run.get("execution_mode")
        if not prev_mode and prev_run.get("compile_only"):
            prev_mode = "compile"
    if not prev_mode and rep_data:
        prev_mode = rep_data.get("execution_mode")
        if not prev_mode and rep_data.get("compile_only"):
            prev_mode = "compile"

    if payload and "execution_mode" in payload and payload["execution_mode"]:
        target_mode = str(payload["execution_mode"]).strip().lower()
    elif prev_mode == "compile":
        target_mode = "compile"
    else:
        target_mode = "run"

    is_compile = (target_mode == "compile")

    verify_rerun = prev_run.get("verify_rerun", True) if prev_run else True
    display_name = prev_run.get("project_name", project_dir.name) if prev_run else project_dir.name
    if not old_db:
        raise HTTPException(status_code=400, detail="The project session has no database input to continue from.")

    RUNS_IN_FLIGHT[new_run_id] = {
        "run_id": new_run_id,
        "shell_token": shell_token,
        "session_id": session_id,
        "session_token": session["session_token"],
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": "",
        "project_name": display_name,
        "project_dir": str(project_dir),
        "source_type": prev_run.get("source_type", "zip") if prev_run else "zip",
        "git_url": prev_run.get("git_url") if prev_run else None,
        "git_branch": prev_run.get("git_branch") if prev_run else None,
        "database_location": str(old_db),
        "data_location": str(old_data) if old_data else "",
        "verify_rerun": verify_rerun,
        "staging_dir": str(staging_dir),
        "ingested_tables": prev_run.get("ingested_tables", []) if prev_run else [],
        "log_file": str(RUN_LOGS_DIR / f"run_{new_run_id}.log"),
        "structured_log_file": str(RUN_LOGS_DIR / f"run_{new_run_id}.events.jsonl"),
        "report_file": str(RUN_LOGS_DIR / f"run_{new_run_id}.json"),
        "compile_only": is_compile,
        "execution_mode": target_mode,
        "full_refresh": full_refresh,
        "select": select_val,
        "error": None,
        "container_name": session["container_name"],
        "container_workspace": session["workspace"],
        "container_project_dir": f"/workspace/runs/{new_run_id}/runtime/project",
        "container_input_project": "/input/" + project_dir.resolve().relative_to(staging_dir.resolve()).as_posix(),
        "database_type": prev_run.get("database_type", "unknown") if prev_run else (rep_data.get("database_type", "unknown") if rep_data else "unknown"),
        "run_config_path": str(run_config_path),
    }
    session["status"] = "running"
    session["active_run_id"] = new_run_id
    session["latest_run_id"] = new_run_id
    session["last_seen"] = time.monotonic()
    session.setdefault("run_ids", []).append(new_run_id)

    background_tasks.add_task(
        _execute_run_worker,
        new_run_id,
        project_dir,
        old_db,
        old_data,
        verify_rerun,
        is_compile,
        target_mode,
        full_refresh,
        select_val,
        run_config_path,
        session_id,
    )

    mode_name = "dbt compile" if is_compile else "dbt run"
    run_desc = f"Full refresh ({mode_name})" if full_refresh else f"Pipeline run ({mode_name})"
    return {
        "status": "started",
        "run_id": new_run_id,
        "session_id": session_id,
        "session_token": session["session_token"],
        "shell_token": shell_token,
        "message": f"{run_desc} started ({new_run_id}).",
        "execution_mode": target_mode,
        "compile_only": is_compile,
        "full_refresh": full_refresh,
        "select": select_val,
    }


def _get_manifest_path(run_id: str) -> Path | None:
    """Find manifest.json for a given run ID from container runs, uploads, or workspace."""
    # Each logical run gets its own target directory within a reused session container.
    info = RUNS_IN_FLIGHT.get(run_id)
    session_id = str((info or {}).get("session_id") or run_id)
    candidate = CONTAINER_RUNS_DIR / session_id / "runs" / run_id / "runtime" / "target" / "manifest.json"
    if candidate.is_file():
        return candidate

    # 2. In-flight container workspace
    if info:
        ws = info.get("container_workspace")
        if ws:
            p = Path(ws) / "runs" / run_id / "runtime" / "target" / "manifest.json"
            if p.is_file():
                return p
        staging = info.get("staging_dir")
        if staging:
            for p in Path(staging).rglob("manifest.json"):
                if p.is_file() and p.parent.name == "target":
                    return p

    # 3. Check staging / uploads dir on disk
    staging_dir = UPLOADS_DIR / run_id
    if staging_dir.is_dir():
        for p in staging_dir.rglob("manifest.json"):
            if p.is_file() and p.parent.name == "target":
                return p

    # 4. Check container_runs dir on disk
    run_ws = CONTAINER_RUNS_DIR / session_id / "runs" / run_id
    if run_ws.is_dir():
        for p in run_ws.rglob("manifest.json"):
            if p.is_file() and p.parent.name == "target":
                return p

    return None


def _discover_project_incremental_models(run_id: str) -> list[dict[str, Any]]:
    """Discover models configured with materialized='incremental' from project manifest."""
    report_file = RUN_LOGS_DIR / f"run_{run_id}.json"
    report_data: dict[str, Any] = {}
    if report_file.is_file():
        try:
            report_data = json.loads(report_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Map previous model execution statuses if available
    exec_statuses: dict[str, str] = {}
    model_executions = report_data.get("model_executions") or []
    if not model_executions:
        info = RUNS_IN_FLIGHT.get(run_id)
        if info and isinstance(info.get("report"), dict):
            model_executions = info["report"].get("model_executions", [])
    for m in model_executions:
        m_name = m.get("model") or m.get("name")
        if m_name:
            exec_statuses[str(m_name)] = str(m.get("execution_status") or m.get("status") or "passed")

    manifest_path = _get_manifest_path(run_id)
    models: list[dict[str, Any]] = []

    if manifest_path and manifest_path.is_file():
        discovered = discover_incremental_models(manifest_path)
        for d in discovered:
            name = str(d.get("name") or "")
            m_copy = dict(d)
            m_copy["execution_status"] = exec_statuses.get(name, "not_run")
            models.append(m_copy)
    elif report_data.get("incremental_models"):
        for d in report_data["incremental_models"]:
            name = str(d.get("name") or "")
            m_copy = dict(d)
            m_copy["execution_status"] = exec_statuses.get(name, d.get("execution_status", "not_run"))
            models.append(m_copy)

    return models


@app.get("/api/runs/{run_id}/incremental-models")
def get_incremental_models(run_id: str) -> dict[str, Any]:
    """Return all models in the project configured with materialized='incremental'."""
    report_file = RUN_LOGS_DIR / f"run_{run_id}.json"
    if not report_file.is_file() and run_id not in RUNS_IN_FLIGHT:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    models = _discover_project_incremental_models(run_id)
    return {
        "run_id": run_id,
        "incremental_models": models,
        "count": len(models),
    }


@app.post("/api/runs/{run_id}/full-refresh")
async def trigger_full_refresh(
    run_id: str,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = dict(payload or {})
    p.setdefault("execution_mode", "run")

    raw_models = p.get("models")
    all_incremental = bool(p.get("all_incremental", False))

    if raw_models is not None:
        if not isinstance(raw_models, list):
            raise HTTPException(status_code=400, detail="'models' must be a list of model names")

        # Validate format of each model identifier to prevent injection
        validated_models: list[str] = []
        for m in raw_models:
            if not isinstance(m, str) or not re.fullmatch(r"[a-zA-Z0-9_\.]+", m.strip()):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid model identifier: '{m}'. Only alphanumeric, underscores, and dots are allowed."
                )
            validated_models.append(m.strip())

        if not validated_models and not all_incremental:
            raise HTTPException(status_code=400, detail="At least one incremental model must be selected for full refresh")

        # Validate that selected models belong to the active project and are incremental
        discovered = _discover_project_incremental_models(run_id)
        if discovered:
            valid_names = {
                str(d.get("name") or "") for d in discovered
            } | {
                str(d.get("alias") or "") for d in discovered
            } | {
                str(d.get("unique_id") or "") for d in discovered
            }
            for m in validated_models:
                if m not in valid_names:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Model '{m}' is not an incremental model in project '{run_id}'."
                    )

        if all_incremental or (discovered and len(validated_models) == len(discovered)):
            p["select"] = "config.materialized:incremental"
        else:
            p["select"] = " ".join(validated_models)
    elif all_incremental:
        p["select"] = "config.materialized:incremental"
    elif p.get("select"):
        # Validate select string if passed directly
        clean_select = str(p["select"]).strip()
        parts = clean_select.split()
        for part in parts:
            if not re.fullmatch(r"[a-zA-Z0-9_\.\:\+\-]+", part):
                raise HTTPException(status_code=400, detail=f"Invalid selector token: '{part}'")
        p["select"] = clean_select

    return _launch_rerun(run_id=run_id, full_refresh=True, background_tasks=background_tasks, payload=p)


@app.post("/api/runs/{run_id}/run")
async def trigger_standard_run(
    run_id: str,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = dict(payload or {})
    p.setdefault("execution_mode", "run")
    return _launch_rerun(run_id=run_id, full_refresh=False, background_tasks=background_tasks, payload=p)


@app.post("/api/runs/{run_id}/resume")
async def resume_pipeline_from_source_data(
    run_id: str,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply explicit source preparation choices in a fresh isolated run."""
    values = dict(payload or {})
    mappings = values.get("file_mappings", {})
    approved = values.get("approved_sql_scripts", [])
    if not isinstance(mappings, dict) or not isinstance(approved, list):
        raise HTTPException(status_code=400, detail="Invalid source preparation choices.")
    values["execution_mode"] = "run"
    result = _launch_rerun(run_id=run_id, full_refresh=False, background_tasks=background_tasks, payload=values)
    result["resumed_from_stage"] = "source_data_ready"
    return result


@app.get("/api/runs/{run_id}/stream")
async def stream_run_logs(run_id: str) -> StreamingResponse:
    """Stream real-time log output and event updates via SSE."""
    log_file = RUN_LOGS_DIR / f"run_{run_id}.log"
    report_file = RUN_LOGS_DIR / f"run_{run_id}.json"
    event_file = RUN_LOGS_DIR / f"run_{run_id}.events.jsonl"

    async def event_generator() -> AsyncGenerator[str, None]:
        last_log_pos = 0
        last_event_pos = 0
        iterations_after_finish = 0

        while True:
            # Check for new log text
            if log_file.is_file():
                try:
                    with log_file.open("r", encoding="utf-8", errors="replace") as f:
                        f.seek(last_log_pos)
                        new_text = f.read()
                        last_log_pos = f.tell()
                        if new_text:
                            for line in new_text.splitlines():
                                payload = json.dumps({"type": "log", "line": line})
                                yield f"data: {payload}\n\n"
                except Exception:
                    pass

            if event_file.is_file():
                try:
                    with event_file.open("r", encoding="utf-8", errors="replace") as f:
                        f.seek(last_event_pos)
                        event_text = f.read()
                        last_event_pos = f.tell()
                        for raw_event in event_text.splitlines():
                            try:
                                record = json.loads(raw_event)
                            except json.JSONDecodeError:
                                continue
                            if record.get("event") == "stage_transition":
                                payload = json.dumps({
                                    "type": "stage", "stage_id": record.get("stage_id"),
                                    "status": record.get("status"), "summary": record.get("summary"),
                                    "details": record.get("details", {}),
                                })
                                yield f"data: {payload}\n\n"
                            elif record.get("event") == "command_output":
                                payload = json.dumps({"type": "stage_log", "stage": record.get("step"), "stream": record.get("stream"), "line": record.get("line")})
                                yield f"data: {payload}\n\n"
                except Exception:
                    pass

            # Check if run has completed
            is_done = False
            status = "running"
            run_info = RUNS_IN_FLIGHT.get(run_id)
            if run_info and run_info.get("status") == "cancelled":
                is_done = True
                status = "cancelled"
            elif report_file.is_file():
                try:
                    rep = json.loads(report_file.read_text(encoding="utf-8"))
                    is_done = True
                    status = rep.get("overall_status", "passed")
                except Exception:
                    pass
            elif run_id in RUNS_IN_FLIGHT and RUNS_IN_FLIGHT[run_id].get("status") in {"passed", "failed", "needs_configuration", "cancelled"}:
                is_done = True
                status = RUNS_IN_FLIGHT[run_id]["status"]

            if is_done:
                iterations_after_finish += 1
                if iterations_after_finish > 2:
                    payload = json.dumps({"type": "complete", "status": status, "run_id": run_id})
                    yield f"data: {payload}\n\n"
                    break

            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# Mount built frontend if it exists
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
