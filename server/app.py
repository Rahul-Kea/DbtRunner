from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Ensure src/ is importable
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dbt_runner.config import PROJECT_ROOT, RunnerConfig, load_config
from dbt_runner.models import RunReport
from dbt_runner.runner import run_project, save_report

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

# In-memory tracking of active/recent runs
RUNS_IN_FLIGHT: dict[str, dict[str, Any]] = {}


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



def _execute_run_worker(
    run_id: str,
    project_dir: Path,
    database_path: Path,
    data_dir: Path,
    threads: int,
    verify_rerun: bool,
    compile_only: bool = False,
) -> None:
    try:
        from dataclasses import replace
        base_config = load_config()
        config = replace(base_config, threads=threads, verify_rerun=verify_rerun, compile_only=compile_only)

        report = run_project(
            project=project_dir,
            database_or_data=database_path,
            metadata_or_none=data_dir,
            config=config,
            verify_rerun=verify_rerun,
            run_id=run_id,
        )
        if run_id in RUNS_IN_FLIGHT:
            RUNS_IN_FLIGHT[run_id]["status"] = report.overall_status
            RUNS_IN_FLIGHT[run_id]["finished_at"] = report.finished_at
            RUNS_IN_FLIGHT[run_id]["report"] = asdict(report)
    except Exception as exc:
        if run_id in RUNS_IN_FLIGHT:
            RUNS_IN_FLIGHT[run_id]["status"] = "failed"
            RUNS_IN_FLIGHT[run_id]["error"] = str(exc)
            RUNS_IN_FLIGHT[run_id]["finished_at"] = datetime.now(timezone.utc).isoformat()


from .ingestion import build_ducklake_from_raw_data


@app.post("/api/run")
async def start_run(
    project_zip: UploadFile | None = File(None, description="Zip file containing dbt project"),
    git_url: str | None = Form(None, description="Git repository URL containing dbt project"),
    git_branch: str | None = Form(None, description="Git branch, tag or commit"),
    raw_data_files: list[UploadFile] = File(default=[], description="Raw data files (.csv, .parquet, .json, .zip)"),
    threads: int = Form(1),
    verify_rerun: bool = Form(True),
    compile_only: bool = Form(False),
) -> dict[str, Any]:
    run_id = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
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

            for upload in all_raw_uploads:
                filename = upload.filename or "data.csv"
                is_zip = filename.lower().endswith(".zip")

                if is_zip:
                    temp_raw_zip = staging_dir / f"raw_zip_{filename}"
                    with temp_raw_zip.open("wb") as f:
                        shutil.copyfileobj(upload.file, f)
                    _extract_zip(temp_raw_zip, raw_data_staging)
                else:
                    dest_file = raw_data_staging / filename
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

    RUNS_IN_FLIGHT[run_id] = {
        "run_id": run_id,
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
        "threads": threads,
        "verify_rerun": verify_rerun,
        "staging_dir": str(staging_dir),
        "ingested_tables": ingested_tables,
        "log_file": str(RUN_LOGS_DIR / f"run_{run_id}.log"),
        "structured_log_file": str(RUN_LOGS_DIR / f"run_{run_id}.events.jsonl"),
        "report_file": str(RUN_LOGS_DIR / f"run_{run_id}.json"),
        "compile_only": compile_only,
        "error": None,
    }

    # Run in background worker thread
    thread = threading.Thread(
        target=_execute_run_worker,
        args=(run_id, project_dir, db_dest, data_dir, threads, verify_rerun, compile_only),
        daemon=True,
    )
    thread.start()

    return {
        "run_id": run_id,
        "status": "running",
        "started_at": RUNS_IN_FLIGHT[run_id]["started_at"],
        "project_name": display_name,
        "source_type": "git" if has_git else "zip",
        "compile_only": compile_only,
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
                })
            except Exception:
                pass

    return runs


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    report_file = RUN_LOGS_DIR / f"run_{run_id}.json"
    if report_file.is_file():
        try:
            data = json.loads(report_file.read_text(encoding="utf-8"))
            if run_id in RUNS_IN_FLIGHT and RUNS_IN_FLIGHT[run_id].get("ingested_tables"):
                data["ingested_tables"] = RUNS_IN_FLIGHT[run_id]["ingested_tables"]
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
