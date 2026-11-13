"""Private-data paths and validation shared by the grade fetcher and tests."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def resolve_data_dir(
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    system: str | None = None,
) -> Path:
    """Return a per-user data directory outside the project / OneDrive folder."""
    env = os.environ if environ is None else environ
    home_dir = Path.home() if home is None else Path(home)
    platform = os.name if system is None else system

    override = env.get("GRADE_FETCHER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if platform == "nt":
        base = env.get("LOCALAPPDATA")
        return (Path(base) if base else home_dir / "AppData" / "Local") / "GradeFetcher"
    base = env.get("XDG_DATA_HOME")
    return (Path(base) if base else home_dir / ".local" / "share") / "grade-fetcher"


def validate_grades_data(data: object) -> None:
    """Raise ValueError unless data matches the current or legacy export schema."""
    if isinstance(data, list):
        terms = data
    elif isinstance(data, dict) and isinstance(data.get("terms"), list):
        terms = data["terms"]
        overall = data.get("overall")
        if overall is not None and not isinstance(overall, dict):
            raise ValueError("overall must be an object or null")
    else:
        raise ValueError("Expected an object containing a terms array, or a legacy terms array")

    for index, term in enumerate(terms):
        if not isinstance(term, dict):
            raise ValueError(f"term {index + 1} must be an object")
        if not isinstance(term.get("term"), str) or not isinstance(term.get("courses"), list):
            raise ValueError(f"term {index + 1} must contain a term string and courses array")
        summary = term.get("summary")
        if summary is not None and not isinstance(summary, dict):
            raise ValueError(f"term {index + 1} summary must be an object or null")
        if any(not isinstance(course, dict) for course in term["courses"]):
            raise ValueError(f"term {index + 1} courses must contain only objects")
