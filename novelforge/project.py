"""On-disk project helpers."""

from __future__ import annotations

from pathlib import Path

import yaml

from novelforge.llm.routing import default_routing_yaml
from novelforge.schema.canon import Canon
from novelforge.store import save_genre_id

EMPTY_CANON_YAML = yaml.safe_dump(
    Canon().model_dump(mode="json"),
    allow_unicode=True,
    sort_keys=False,
)

PROJECT_SUBDIRS = ("scenes", "manuscript")


def create_project(name: str, root: Path | None = None, genre: str | None = None) -> Path:
    """Create `projects/<name>/` with an empty canon, model routing, and work dirs."""

    base = root if root is not None else Path.cwd()
    project_dir = base / "projects" / name
    if project_dir.exists():
        raise FileExistsError(f"project already exists: {project_dir}")
    project_dir.mkdir(parents=True)
    (project_dir / "canon.yaml").write_text(EMPTY_CANON_YAML, encoding="utf-8")
    (project_dir / "models.yaml").write_text(default_routing_yaml(), encoding="utf-8")
    for subdir in PROJECT_SUBDIRS:
        (project_dir / subdir).mkdir()
        (project_dir / subdir / ".gitkeep").touch()
    if genre is not None:
        save_genre_id(project_dir, genre)
    return project_dir
