from __future__ import annotations

import asyncio
import atexit
import json
import os
import re
import secrets
import shutil
import signal
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

SHELL_SESSIONS: dict[str, dict[str, Any]] = {}
SHELL_SESSION_LOCK = asyncio.Lock()
RUN_IMAGE_BUILD_LOCK = threading.Lock()
DOCKER_EXECUTABLE = shutil.which("docker")
RUN_IMAGE_BUILT = False


def _extract_zip(zip_path: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Protect against path traversal (Zip Slip)
        for member in zf.infolist():
            member_path = Path(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                continue
            zf.extract(member, target_dir)


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
) -> None:
    staging_dir = (UPLOADS_DIR / run_id).resolve()
    workspace = (CONTAINER_RUNS_DIR / run_id).resolve()
    container_name = f"dbt-run-{run_id}"
    info = RUNS_IN_FLIGHT.get(run_id)
    log_path = RUN_LOGS_DIR / f"run_{run_id}.log"
    event_path = RUN_LOGS_DIR / f"run_{run_id}.events.jsonl"
    report_path = RUN_LOGS_DIR / f"run_{run_id}.json"

    try:
        if not project_dir.resolve(strict=True).is_relative_to(staging_dir):
            raise ValueError("Project path is outside this run's uploaded workspace")
        if not database_path.resolve(strict=True).is_relative_to(staging_dir):
            raise ValueError("Database path is outside this run's uploaded workspace")
        if data_dir and not data_dir.resolve(strict=True).is_relative_to(staging_dir):
            raise ValueError("Data path is outside this run's uploaded workspace")
        if os.getuid() == 0:
            raise RuntimeError("Run the web server as an unprivileged user so run containers do not run as root.")

        workspace.mkdir(parents=True, exist_ok=False)
        (workspace / "home").mkdir()
        container_log_dir = workspace / "logs"
        container_log_dir.mkdir()
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

        _ensure_run_image()
        docker = DOCKER_EXECUTABLE or shutil.which("docker")
        assert docker is not None
        project_input = _container_input_path(project_dir, staging_dir)
        database_input = _container_input_path(database_path, staging_dir)
        data_input = _container_input_path(data_dir, staging_dir) if data_dir else None

        docker_args = [
            docker, "run", "--detach", "--init", "--name", container_name,
            "--label", "dbt-runner.managed=true",
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
            RUN_IMAGE,
            "python", "/app/server/container_worker.py",
            "--run-id", run_id,
            "--project-dir", project_input,
            "--database", database_input,
            "--sandbox-dir", "/workspace/runtime",
            "--execution-mode", "compile" if compile_only or execution_mode == "compile" else "run",
        ]
        if data_input:
            docker_args.extend(["--data-dir", data_input])
        if verify_rerun:
            docker_args.append("--verify-rerun")
        if compile_only:
            docker_args.append("--compile-only")
        if full_refresh:
            docker_args.append("--full-refresh")
        if select:
            docker_args.extend(["--select", select])

        launched = subprocess.run(docker_args, capture_output=True, text=True, timeout=120)
        if launched.returncode:
            raise RuntimeError((launched.stderr or launched.stdout or "Docker did not start the run container.").strip())
        if info is not None:
            info["container_id"] = launched.stdout.strip()
            info["container_name"] = container_name

        deadline = time.monotonic() + 8 * 60 * 60
        next_inspect = 0.0
        while time.monotonic() < deadline:
            try:
                container_report = json.loads(report_path.read_text(encoding="utf-8"))
                if container_report.get("finished_at") and container_report.get("overall_status") in {"passed", "failed"}:
                    replacements = [
                        ("/app/run_logs", str(RUN_LOGS_DIR)),
                        ("/workspace", str(workspace)),
                        ("/input", str(staging_dir)),
                    ]
                    normalized = _replace_container_paths(container_report, replacements)
                    report_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                    if info is not None:
                        info["status"] = normalized["overall_status"]
                        info["finished_at"] = normalized.get("finished_at", datetime.now(timezone.utc).isoformat())
                        info["report"] = normalized
                        info["database_location"] = normalized.get("ducklake_metadata_location", info.get("database_location"))
                        info["data_location"] = normalized.get("data_location") or None
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
        docker = DOCKER_EXECUTABLE or shutil.which("docker")
        if docker:
            try:
                subprocess.run([docker, "rm", "--force", container_name], capture_output=True, timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                pass
        _fail_container_run(run_id, str(exc))


def _cleanup_run_containers() -> None:
    docker = DOCKER_EXECUTABLE or shutil.which("docker")
    if not docker:
        return
    for info in list(RUNS_IN_FLIGHT.values()):
        container_name = info.get("container_name")
        if container_name:
            try:
                subprocess.run([docker, "rm", "--force", container_name], capture_output=True, timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                pass


atexit.register(_cleanup_run_containers)


from .ingestion import build_ducklake_from_raw_data


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
) -> dict[str, Any]:
    run_id = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    shell_token = secrets.token_urlsafe(32)
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

        # 2. Build Lakehouse from raw data if uploaded, or initialize self-contained / seed mode
        if all_raw_uploads:
            raw_data_staging = staging_dir / "raw_data"
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

            # Auto-generate DuckLake catalog & partitioned Parquet files
            lake_meta = staging_dir / "lake.ducklake"
            lake_data = staging_dir / "lake_data"
            ingested_tables = build_ducklake_from_raw_data(
                raw_data_dir=raw_data_staging,
                lake_metadata_path=lake_meta,
                lake_data_dir=lake_data,
                default_schema="main",
            )
            db_dest = lake_meta
            data_dir = lake_data
        else:
            # Seed-only / self-contained mode: dbt project contains seeds/ CSVs
            lake_meta = staging_dir / "lake.ducklake"
            lake_data = staging_dir / "lake_data"
            lake_data.mkdir(parents=True, exist_ok=True)
            import duckdb
            init_con = duckdb.connect(":memory:")
            try:
                init_con.execute("LOAD ducklake;")
                init_con.execute(
                    f"ATTACH 'ducklake:{lake_meta.resolve()}' AS lake (DATA_PATH '{lake_data.resolve()}');"
                )
                init_con.execute("CHECKPOINT lake;")
            finally:
                init_con.close()
            db_dest = lake_meta
            data_dir = lake_data

    except ValueError as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to process uploaded data: {exc}")

    clean_select = select.strip() if select and select.strip() else None
    effective_compile = compile_only or execution_mode == "compile"
    effective_mode = "compile" if effective_compile else "run"

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
        "container_name": f"dbt-run-{run_id}",
        "container_workspace": str(CONTAINER_RUNS_DIR / run_id),
        "container_project_dir": "/workspace/runtime/project",
        "container_input_project": "/input/" + project_dir.resolve().relative_to(staging_dir.resolve()).as_posix(),
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
    )

    return {
        "run_id": run_id,
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
            "database_type": "ducklake",
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
                    "database_type": data.get("database_type", "ducklake"),
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

        async with SHELL_SESSION_LOCK:
            session = SHELL_SESSIONS.get(run_id)
            if session is None:
                session = {"lock": asyncio.Lock()}
                SHELL_SESSIONS[run_id] = session

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
            expected_project = host_workspace / "runtime" / "project"
            container_workdir = "/workspace/runtime/project"
            for _ in range(600):
                if expected_project.is_dir() or run_info.get("status") in {"passed", "failed"}:
                    break
                await asyncio.sleep(0.1)
            if not expected_project.is_dir():
                container_workdir = run_info.get("container_input_project", "/workspace")

            master_fd, slave_fd = pty.openpty()
            docker_args = [
                docker, "exec", "--interactive", "--tty",
                "--workdir", container_workdir,
                "--env", "HOME=/workspace/home",
                "--env", "DBT_PROFILES_DIR=/workspace/runtime/profiles",
                "--env", "DBT_TARGET_PATH=/workspace/runtime/target",
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
    """Remove a finished run's container while preserving its sandbox files."""
    run_info = RUNS_IN_FLIGHT.get(run_id)
    expected_token = run_info.get("shell_token", "") if run_info else ""
    supplied_token = str(payload.get("shell_token") or "")
    if not expected_token or not secrets.compare_digest(supplied_token, expected_token):
        raise HTTPException(status_code=403, detail="Run access token is invalid or expired")
    if run_info.get("status") not in {"passed", "failed"}:
        raise HTTPException(status_code=409, detail="The run container can only be destroyed after the run finishes")
    if run_info.get("container_destroyed"):
        return {"run_id": run_id, "container_destroyed": True, "workspace_preserved": True}

    container_name = run_info.get("container_name")
    if not container_name:
        raise HTTPException(status_code=404, detail="Run container was not found")
    docker = DOCKER_EXECUTABLE or shutil.which("docker")
    if not docker:
        raise HTTPException(status_code=503, detail="Docker is unavailable")
    try:
        result = subprocess.run(
            [docker, "rm", "--force", container_name],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=503, detail=f"Could not remove the run container: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "Docker could not remove the run container.").strip()
        if "No such container" in detail or "No such object" in detail:
            run_info["container_destroyed"] = True
            SHELL_SESSIONS.pop(run_id, None)
            return {"run_id": run_id, "container_destroyed": True, "workspace_preserved": True}
        raise HTTPException(status_code=502, detail=detail)

    run_info["container_destroyed"] = True
    SHELL_SESSIONS.pop(run_id, None)
    return {"run_id": run_id, "container_destroyed": True, "workspace_preserved": True}


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
        containers.append({
            "container_id": str(docker_row.get("ID") or ""),
            "name": str(docker_row.get("Names") or ""),
            "image": str(docker_row.get("Image") or ""),
            "status": str(docker_row.get("Status") or "unknown"),
            "created": str(docker_row.get("CreatedAt") or ""),
            "run_id": labels.get("dbt-runner.run-id", ""),
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
    label_format = '{{ index .Config.Labels "dbt-runner.managed" }}|{{ index .Config.Labels "dbt-runner.run-id" }}'
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
    managed_label, _, run_id = inspected.stdout.strip().partition("|")
    if managed_label != "true":
        raise HTTPException(status_code=403, detail="This container is not managed by dbt Runner")
    run_info = RUNS_IN_FLIGHT.get(run_id)
    expected_token = str((run_info or {}).get("shell_token") or "")
    supplied_token = str(payload.get("shell_token") or "")
    if not expected_token or not secrets.compare_digest(supplied_token, expected_token):
        raise HTTPException(status_code=403, detail="Run access token is invalid or unavailable")

    try:
        removed = subprocess.run(
            [docker, "rm", "--force", container_id],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=503, detail=f"Could not remove Docker container: {exc}") from exc
    if removed.returncode:
        detail = (removed.stderr or removed.stdout or "Docker could not remove the container.").strip()
        raise HTTPException(status_code=502, detail=detail)

    if run_info:
        run_info["container_destroyed"] = True
    SHELL_SESSIONS.pop(run_id, None)
    return {"container_id": container_id, "run_id": run_id, "container_destroyed": True}


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
            return data
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not read report file: {exc}")

    if run_id in RUNS_IN_FLIGHT:
        info = RUNS_IN_FLIGHT[run_id]
        return {
            "run_id": run_id,
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
    schema: str = "main",
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
    clean_schema = schema.split(".")[-1] if schema else "main"

    db_path_str = run_info.get("database_location") or report_data.get("ducklake_metadata_location")
    data_dir_str = run_info.get("data_location") or report_data.get("data_location")
    db_type = report_data.get("database_type") or ("ducklake" if db_path_str and "ducklake" in db_path_str else "duckdb")

    # 1. Attempt live query if database file exists on disk
    if db_path_str and Path(db_path_str).exists():
        try:
            import duckdb
            db_path = Path(db_path_str)
            data_dir = Path(data_dir_str) if data_dir_str else None

            conn = duckdb.connect(":memory:")
            if db_type == "ducklake" and data_dir and data_dir.is_dir():
                conn.execute("INSTALL ducklake; LOAD ducklake;")
                conn.execute(
                    f"ATTACH 'ducklake:{db_path}' AS lake (DATA_PATH '{data_dir}', OVERRIDE_DATA_PATH TRUE, READ_ONLY TRUE)"
                )
                cat_name = "lake"
            else:
                conn.execute(f"ATTACH '{db_path}' AS lake (READ_ONLY)")
                cat_name = "lake"

            cnt_row = conn.execute(f'SELECT COUNT(*) FROM "{cat_name}"."{clean_schema}"."{clean_table}"').fetchone()
            row_count = cnt_row[0] if cnt_row else 0

            cur = conn.execute(f'SELECT * FROM "{cat_name}"."{clean_schema}"."{clean_table}" LIMIT {limit}')
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
            obj_sch = obj.get("schema") or "main"
            if obj_name == clean_table and (not schema or obj_sch == clean_schema):
                return {
                    "status": "success",
                    "run_id": run_id,
                    "database": obj.get("database", "ducklake"),
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

    staging_dir = Path(prev_run["staging_dir"]) if prev_run and "staging_dir" in prev_run else None
    if not staging_dir or not staging_dir.is_dir():
        candidate = UPLOADS_DIR / run_id
        if candidate.is_dir():
            staging_dir = candidate

    project_dir_str = (prev_run.get("project_dir") if prev_run else None) or (rep_data.get("project_dir") if rep_data else None)
    if not project_dir_str or not Path(project_dir_str).is_dir():
        raise HTTPException(status_code=400, detail=f"Project directory for run {run_id} not found.")

    old_project_dir = Path(project_dir_str)
    old_db_str = (prev_run.get("database_location") if prev_run else None) or (rep_data.get("ducklake_metadata_location") if rep_data else "")
    old_data_str = (prev_run.get("data_location") if prev_run else None) or (rep_data.get("data_location") if rep_data else "")

    old_db = Path(old_db_str) if old_db_str else None
    old_data = Path(old_data_str) if old_data_str else None

    new_run_id = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    shell_token = secrets.token_urlsafe(32)
    new_staging_dir = UPLOADS_DIR / new_run_id
    new_staging_dir.mkdir(parents=True, exist_ok=True)

    # Copy project
    new_proj_extract = new_staging_dir / "project"
    if staging_dir and (staging_dir / "project").is_dir():
        shutil.copytree(staging_dir / "project", new_proj_extract)
        try:
            rel = old_project_dir.relative_to(staging_dir / "project")
            new_project_dir = new_proj_extract / rel
        except ValueError:
            new_project_dir = new_proj_extract
    else:
        shutil.copytree(old_project_dir, new_proj_extract)
        new_project_dir = new_proj_extract

    # Copy database metadata file
    new_db = None
    if old_db and old_db.is_file():
        new_db = new_staging_dir / old_db.name
        shutil.copy2(old_db, new_db)
    elif staging_dir and (staging_dir / "lake.ducklake").is_file():
        new_db = new_staging_dir / "lake.ducklake"
        shutil.copy2(staging_dir / "lake.ducklake", new_db)

    # Copy data directory (e.g. Parquet storage)
    new_data = None
    if old_data and old_data.is_dir():
        new_data = new_staging_dir / old_data.name
        shutil.copytree(old_data, new_data)
    elif staging_dir and (staging_dir / "lake_data").is_dir():
        new_data = new_staging_dir / "lake_data"
        shutil.copytree(staging_dir / "lake_data", new_data)

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
    display_name = prev_run.get("project_name", new_project_dir.name) if prev_run else new_project_dir.name

    RUNS_IN_FLIGHT[new_run_id] = {
        "run_id": new_run_id,
        "shell_token": shell_token,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": "",
        "project_name": display_name,
        "project_dir": str(new_project_dir),
        "source_type": prev_run.get("source_type", "zip") if prev_run else "zip",
        "git_url": prev_run.get("git_url") if prev_run else None,
        "git_branch": prev_run.get("git_branch") if prev_run else None,
        "database_location": str(new_db) if new_db else "",
        "data_location": str(new_data) if new_data else "",
        "verify_rerun": verify_rerun,
        "staging_dir": str(new_staging_dir),
        "ingested_tables": prev_run.get("ingested_tables", []) if prev_run else [],
        "log_file": str(RUN_LOGS_DIR / f"run_{new_run_id}.log"),
        "structured_log_file": str(RUN_LOGS_DIR / f"run_{new_run_id}.events.jsonl"),
        "report_file": str(RUN_LOGS_DIR / f"run_{new_run_id}.json"),
        "compile_only": is_compile,
        "execution_mode": target_mode,
        "full_refresh": full_refresh,
        "select": select_val,
        "error": None,
        "container_name": f"dbt-run-{new_run_id}",
        "container_workspace": str(CONTAINER_RUNS_DIR / new_run_id),
        "container_project_dir": "/workspace/runtime/project",
        "container_input_project": "/input/" + new_project_dir.resolve().relative_to(new_staging_dir.resolve()).as_posix(),
    }

    background_tasks.add_task(
        _execute_run_worker,
        new_run_id,
        new_project_dir,
        new_db,
        new_data,
        verify_rerun,
        is_compile,
        target_mode,
        full_refresh,
        select_val,
    )

    mode_name = "dbt compile" if is_compile else "dbt run"
    run_desc = f"Full refresh ({mode_name})" if full_refresh else f"Pipeline run ({mode_name})"
    return {
        "status": "started",
        "run_id": new_run_id,
        "shell_token": shell_token,
        "message": f"{run_desc} started ({new_run_id}).",
        "execution_mode": target_mode,
        "compile_only": is_compile,
        "full_refresh": full_refresh,
        "select": select_val,
    }


@app.post("/api/runs/{run_id}/full-refresh")
async def trigger_full_refresh(
    run_id: str,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _launch_rerun(run_id=run_id, full_refresh=True, background_tasks=background_tasks, payload=payload)


@app.post("/api/runs/{run_id}/run")
async def trigger_standard_run(
    run_id: str,
    background_tasks: BackgroundTasks,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = dict(payload or {})
    p.setdefault("execution_mode", "run")
    return _launch_rerun(run_id=run_id, full_refresh=False, background_tasks=background_tasks, payload=p)


@app.get("/api/runs/{run_id}/stream")
async def stream_run_logs(run_id: str) -> StreamingResponse:
    """Stream real-time log output and event updates via SSE."""
    log_file = RUN_LOGS_DIR / f"run_{run_id}.log"
    report_file = RUN_LOGS_DIR / f"run_{run_id}.json"

    async def event_generator() -> AsyncGenerator[str, None]:
        last_log_pos = 0
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

            # Check if run has completed
            is_done = False
            status = "running"
            if report_file.is_file():
                try:
                    rep = json.loads(report_file.read_text(encoding="utf-8"))
                    is_done = True
                    status = rep.get("overall_status", "passed")
                except Exception:
                    pass
            elif run_id in RUNS_IN_FLIGHT and RUNS_IN_FLIGHT[run_id].get("status") in {"passed", "failed"}:
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
