"""Load the pinned public skill catalog without network or user-home discovery."""

from functools import lru_cache
from pathlib import Path

from openhands.sdk.skills.skill import Skill, load_marketplace_skill_names
from openhands.sdk.skills.utils import find_regular_md_files, find_skill_md_directories


@lru_cache(maxsize=4)
def _load_skills(root_value: str):
    root = Path(root_value)
    directory = root / "skills"
    names = load_marketplace_skill_names(root, "marketplaces/default.json")
    if names is None:
        modern = find_skill_md_directories(directory)
        paths = list(modern) + list(find_regular_md_files(directory, {p.parent for p in modern}))
    else:
        paths = []
        for name in sorted(names):
            modern = directory / name / "SKILL.md"
            legacy = directory / f"{name}.md"
            if modern.is_file():
                paths.append(modern)
            elif legacy.is_file():
                paths.append(legacy)
    return tuple(
        skill
        for path in sorted(paths)
        if (skill := Skill.load(path, skill_base_dir=root)) is not None
    )


def load_skills(root: Path):
    return list(_load_skills(str(root.resolve())))
