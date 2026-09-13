"""
clipping.story.loader — JSON parser & validator for Story Clip.

Parses and validates:
  - sources.json      -> the registry of source videos
  - story_recipe.json -> the story recipe (clips, scenes, hook, highlight)
"""

import json
import os
from types import SimpleNamespace

SUPPORTED_PLATFORMS = {"youtube", "tiktok", "instagram", "gdrive", "local"}

_REQUIRED_SOURCE_FIELDS = {"id", "name", "platform"}
_REQUIRED_CLIP_FIELDS = {"clip_id", "title", "hook", "highlight"}
_REQUIRED_SCENE_FIELDS = {"source_id"}


# ==============================================================================
# SOURCES.JSON
# ==============================================================================

def load_sources(path: str) -> dict[str, dict]:
    """
    Parse and validate a ``sources.json`` file.

    Returns
    -------
    dict[str, dict]
        Mapping of ``source_id`` -> source entry. Every entry has at least
        ``id``, ``name``, ``platform`` and either ``url`` or ``local_path``.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    ValueError
        If schema validation fails.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Sources file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    entries = raw.get("sources", [])
    if not entries:
        raise ValueError(f"sources.json is empty or has no 'sources' key: {path}")

    registry: dict[str, dict] = {}

    for idx, src in enumerate(entries):
        missing = _REQUIRED_SOURCE_FIELDS - set(src.keys())
        if missing:
            raise ValueError(
                f"Source #{idx} ('{src.get('id', '?')}') is missing required field(s): "
                f"{sorted(missing)}"
            )

        sid = src["id"]
        platform = src["platform"]

        if sid in registry:
            raise ValueError(f"Duplicate source id: '{sid}'")

        if platform not in SUPPORTED_PLATFORMS:
            raise ValueError(
                f"Source '{sid}': unknown platform '{platform}'. "
                f"Choose one of: {sorted(SUPPORTED_PLATFORMS)}"
            )

        if platform == "local":
            local_path = src.get("local_path")
            if not local_path:
                raise ValueError(f"Source '{sid}': platform 'local' requires 'local_path'.")
            if not os.path.exists(local_path):
                raise ValueError(f"Source '{sid}': local_path not found: {local_path}")
        elif not src.get("url"):
            raise ValueError(f"Source '{sid}': platform '{platform}' requires 'url'.")

        registry[sid] = src

    print(f"✅ Loaded {len(registry)} source(s) from {os.path.basename(path)}")
    return registry


# ==============================================================================
# STORY_RECIPE.JSON
# ==============================================================================

def _validate_scene(
    scene: dict, source_registry: dict, clip_id, section: str, idx: int
) -> None:
    """Validate a single scene entry inside a clip."""
    where = f"Clip #{clip_id} -> {section} -> scene #{idx}"

    missing = _REQUIRED_SCENE_FIELDS - set(scene.keys())
    if missing:
        raise ValueError(f"{where}: missing field(s) {sorted(missing)}")

    sid = scene["source_id"]
    if sid not in source_registry:
        raise ValueError(
            f"{where}: source_id '{sid}' is not in sources.json. "
            f"Available IDs: {sorted(source_registry)}"
        )

    start, end = scene.get("start"), scene.get("end")

    # Both timestamps null is allowed — the scene is skipped while rendering.
    if start is None and end is None:
        return
    if start is None or end is None:
        raise ValueError(
            f"{where}: start and end must both be numbers, or both be null "
            f"(got start={start!r}, end={end!r})."
        )
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        raise ValueError(f"{where}: start/end must be numbers or null.")
    if start < 0:
        raise ValueError(f"{where}: start ({start}) cannot be negative.")
    if end <= start:
        raise ValueError(f"{where}: end ({end}) must be greater than start ({start}).")


def load_recipe(path: str, source_registry: dict[str, dict]) -> dict:
    """
    Parse and validate a ``story_recipe.json`` file.

    Returns the validated recipe dict, with a ``_defaults`` namespace merged in
    from ``default_settings``.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    ValueError
        If schema validation fails.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Recipe file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        recipe = json.load(f)

    clips = recipe.get("clips", [])
    if not clips:
        raise ValueError(f"story_recipe.json is empty or has no 'clips' key: {path}")

    seen_ids: set = set()

    for clip in clips:
        missing = _REQUIRED_CLIP_FIELDS - set(clip.keys())
        if missing:
            raise ValueError(
                f"Clip (clip_id={clip.get('clip_id', '?')}): missing field(s) {sorted(missing)}"
            )

        cid = clip["clip_id"]
        if not isinstance(cid, int):
            # Clips are ordered by clip_id later, so mixed types would raise
            # a TypeError deep inside sorted() instead of here.
            raise ValueError(f"clip_id must be an integer, got {cid!r}.")
        if cid in seen_ids:
            raise ValueError(f"Duplicate clip_id: {cid}")
        seen_ids.add(cid)

        for section in ("hook", "highlight"):
            scenes = clip[section].get("scenes", [])
            if not scenes:
                raise ValueError(f"Clip #{cid}: {section}.scenes is empty.")
            for i, scene in enumerate(scenes):
                _validate_scene(scene, source_registry, cid, section, i)

    defaults = recipe.get("default_settings", {})
    recipe["_defaults"] = SimpleNamespace(
        ratio=defaults.get("ratio", "9:16"),
        font_style=defaults.get("font_style", "HORMOZI"),
        use_subtitle=defaults.get("use_subtitle", True),
        use_bgm=defaults.get("use_bgm", True),
        bgm_mood=defaults.get("bgm_mood", "upbeat"),
        min_duration=defaults.get("min_duration", 15),
    )

    print(
        f"✅ Loaded {len(clips)} clip(s) from {os.path.basename(path)} "
        f"(project: {recipe.get('project_name', 'Untitled')})"
    )
    return recipe
