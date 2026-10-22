from __future__ import annotations

from .models import Diagnostic


def classify_failure(text: str, stage_id: str) -> Diagnostic:
    message = text.strip() or "The command failed without returning an error message."
    lower = message.casefold()
    if stage_id in {"environment_ready"} or any(token in lower for token in ("profile", "adapter", "credentials", "connection refused", "could not connect")):
        category = "ConfigurationError"
        action = "Review the selected dbt profile, adapter package, target settings, and credentials."
    elif "locationmismatch" in lower or "location mismatch" in lower:
        category = "LocationMismatch"
        action = "Configure the target or an explicit schema/database mapping so the relation is available at its declared location."
    elif stage_id == "source_data_ready" or "missing required source relation" in lower or "missingsourcedata" in lower:
        category = "MissingSourceData"
        action = "Provide the source relation using a seed, an explicit file mapping, an approved setup script, or an existing warehouse table."
    elif stage_id == "compilation_passed" or any(token in lower for token in ("compilation error", "compilation failed", "syntax error", "undefined macro", "depends on a node")):
        category = "CompilationError"
        action = "Correct the reported dbt YAML, Jinja, macro, ref, source, or SQL compilation issue in the project."
    elif stage_id == "models_executed" and "test" in lower:
        category = "TestFailure"
        action = "Review failed dbt test nodes and the resulting data; adjust the model or test expectation explicitly."
    else:
        category = "ExecutionError"
        action = "Review the database error and failed dbt node, then correct the runtime query or target permissions."
    return Diagnostic(category, message, stage_id, next_action=action)
