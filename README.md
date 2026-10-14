# dbt project runner

`runner.py` runs a dbt project in an isolated DuckDB or DuckLake sandbox. Each run creates
a temporary workspace containing an isolated logical clone of the supplied database
or DuckLake metadata catalog. The supplied project, metadata catalog, and data directory
are read-only inputs; dbt reads and writes only inside the sandbox.

The implementation is split into `src/dbt_runner/`: `cli.py` handles CLI arguments and prompts,
`runner.py` coordinates a run, `project.py` validates and prepares project
inputs, `commands.py` streams subprocess output, `validation.py` verifies DAG topology,
reads dbt artifacts, and validates catalog objects, `config.py` loads runner settings,
`structured_logging.py` writes JSONL events, and `models.py` defines report data.
The root `runner.py` remains the supported entrypoint and compatibility import.

## Start

Install the runner's dependencies:

```sh
python3 -m pip install -r requirements.txt
```

### Web UI (TypeScript Frontend + API Server)

Start the unified Web Application and API server:

```sh
python3 run_web.py
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

From the web UI, the user can provide:
1. **dbt Project Source**: Either upload a `.zip` archive or paste a **Git Repository URL** (cloned with shallow `--depth 1` automatically).
2. **Raw Data Files (`.zip`, `.csv`, `.parquet`, or `.json`)**: The raw business data files (optional if project includes `seeds/`).

**The Application Automatically**:
- Initializes an isolated **DuckLake** catalog metadata store.
- Ingests raw data files into partitioned **Parquet** tables on the fly.
- Configures profiles and connects the lakehouse.
- Runs DAG validation, compiles models, seeds, snapshots, and tests.
- Verifies physical catalog schemas and ensures repeated execution (rerun) idempotency.
- Streams live terminal logs and metrics in real-time.

*(Advanced users who already have pre-built `.ducklake` catalogs can switch to Legacy Mode directly from the UI).*

For frontend developers working on the UI:
```sh
python3 run_web.py --dev
```

### Non-Interactive (CI/CD / Scripted)

```sh
python3 runner.py --project-dir /path/to/project --database /path/to/db.duckdb --non-interactive
```

For DuckLake projects:

```sh
python3 runner.py --project-dir /path/to/project --database /path/to/simulation.ducklake --data-dir /path/to/parquet_data --non-interactive
```

### Interactive CLI

From this directory, run:

```sh
python3 runner.py
```

Or from the `src/` directory:

```sh
python3 -m dbt_runner
```

When prompted, provide:
1. The dbt project directory.
2. The DuckDB database file (.duckdb) or DuckLake metadata catalog location (.ducklake).
3. The DuckLake data directory containing Parquet files (optional for standard DuckDB).

Type `run` to execute the project or `exit` to leave. The runner parses the DAG,
verifies graph dependencies and acyclicity, runs seeds/snapshots/models, executes tests,
validates catalog objects, and performs a safe repeated execution (rerun) to confirm idempotency.
Output is streamed to the terminal and written to both a readable log and a
structured JSONL event log.


## Isolation and cleanup

The runner copies the supplied DuckLake data directory and uses DuckDB's
`COPY FROM DATABASE` to clone the supplied metadata catalog into the temporary
workspace. The generated profile attaches that cloned catalog and overrides
its data path to the copied Parquet directory. This preserves the catalog's
table-to-file mappings while keeping dbt writes isolated from the supplied
catalog. Each run starts from a new clone of the input catalog; it does not
start from an empty catalog. Unsupported/custom model materializations are
rejected unless they are added to the configured safe list. dbt writes its
seeds, models, packages, logs, and
target artifacts into the temporary workspace. DuckDB extensions and temporary
build files are also confined to that workspace, and pip caching is disabled.
The runner removes the entire workspace after the command finishes, including
when dbt fails. The source project and supplied DuckLake locations are not
modified.

The run is valid only when its relation names, database/schema locations, and
table/view kinds match the physical resources in dbt's parsed DAG. Declared
columns must exist, declared types must match their core type families, and
every observed column must have a supported core type. The report includes
expected and observed objects and any validation failures.

The runner preserves only its own readable log, structured event log, and JSON
report in `run_logs/`.
The report records whether sandbox cleanup completed. Copying a large project
or lake can take time and temporary disk space proportional to their size.

## Run artifacts

Each run leaves these persistent artifacts in `run_logs/`:

- `run_<timestamp>.log` contains streamed command output and return codes.
- `run_<timestamp>.events.jsonl` contains timestamped command, output, model,
  validation, cleanup, and run lifecycle events.
- `run_<timestamp>.json` contains step statuses, dbt model/test results,
  expected and observed catalog objects, validation failures, input locations,
  sandbox catalog status, sandbox cleanup status, and per-model object type,
  execution status, duration, relation name, and error message.

Edit `safe_materializations` in `runner_config.json` to control the model
materializations accepted for isolated reruns. The default list supports
`table`, `view`, `incremental`, `ephemeral`, and `materialized_view`.

On exit, the CLI prints a summary of the latest run. The first run needs network
access to install `dbt-duckdb` into its fresh environment and may need network
access to install the DuckDB DuckLake extension into the temporary extension
directory.
