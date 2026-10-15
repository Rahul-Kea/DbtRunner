FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src:/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt runner_config.json /app/
COPY src /app/src
COPY server/container_worker.py /app/server/container_worker.py

RUN pip install --no-cache-dir -r /app/requirements.txt \
    && mkdir -p /app/run_logs /opt/duckdb/extensions /workspace/home \
    && python -c "from pathlib import Path; import duckdb; c=duckdb.connect(); c.execute(\"SET extension_directory='/opt/duckdb/extensions'\"); c.execute('INSTALL ducklake'); c.execute('LOAD ducklake'); assert list(Path('/opt/duckdb/extensions').rglob('ducklake.duckdb_extension')); c.close()" \
    && chmod -R a+rX /opt/duckdb/extensions
