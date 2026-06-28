from __future__ import annotations

from pathlib import Path
from typing import Any

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def is_reference_uri(value: str) -> bool:
    return value.startswith(("http://", "https://", "data:"))


def build_reference_index(
    project_dir: Path,
    *,
    pre_production: dict[str, Any] | None = None,
    design: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Build a lookup table for storyboard reference ids.

    The AI Director can emit ids such as ``char_mira_anchor``,
    ``scene_lab_mood``, or ``style_anchor``. This index maps those ids to
    local files or URLs from pre-production, design, and assets/references.
    """

    pre_production = pre_production or {}
    design = design or {}
    index: dict[str, list[dict[str, Any]]] = {}
    refs_dir = project_dir / "assets" / "references"

    _add_reference(
        index,
        project_dir,
        ["style_anchor", "style"],
        pre_production.get("style_anchor_path") or design.get("style_anchor_path"),
        role="style",
        source="style_anchor_path",
    )
    default_style_anchor = refs_dir / "style_anchor.png"
    if default_style_anchor.exists():
        _add_reference(
            index,
            project_dir,
            ["style_anchor", default_style_anchor.stem],
            str(default_style_anchor),
            role="style",
            source="assets/references",
        )

    for character in pre_production.get("characters", []) or []:
        _index_character(index, project_dir, character, source="pre_production.characters")

    for environment in pre_production.get("environments", []) or []:
        _index_environment(index, project_dir, environment, source="pre_production.environments")

    for character in design.get("characters", []) or []:
        char_id = character.get("char_id")
        ref = character.get("reference_image_url")
        aliases = [
            value for value in [char_id, f"char_{char_id}_anchor" if char_id else ""] if value
        ]
        _add_reference(
            index,
            project_dir,
            aliases,
            ref,
            role="character",
            source="design.characters",
        )

    for chain in design.get("reference_image_chains", []) or []:
        chain_id = chain.get("chain_id")
        values = list(chain.get("reference_urls") or []) + list(
            chain.get("reference_local_paths") or []
        )
        for idx, value in enumerate(values):
            aliases = [chain_id] if chain_id and idx == 0 else []
            if chain_id:
                aliases.append(f"{chain_id}_{idx + 1}")
            _add_reference(
                index,
                project_dir,
                aliases,
                value,
                role=chain.get("chain_type") or "reference",
                source="design.reference_image_chains",
            )

    if refs_dir.exists():
        for path in sorted(refs_dir.glob("*")):
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            _add_reference(
                index,
                project_dir,
                [path.stem],
                str(path),
                role=_infer_role(path.stem),
                source="assets/references",
            )

    return index


def resolve_reference_assets_for_shot(
    project_dir: Path,
    *,
    contract: dict[str, Any] | None = None,
    design_segment: dict[str, Any] | None = None,
    pre_production: dict[str, Any] | None = None,
    design: dict[str, Any] | None = None,
    include_style_anchor: bool = True,
) -> dict[str, Any]:
    contract = contract or {}
    design_segment = design_segment or {}
    binding = contract.get("storyboard_binding", {}) if isinstance(contract, dict) else {}
    index = build_reference_index(
        project_dir,
        pre_production=pre_production,
        design=design,
    )

    storyboard_ids = _as_list(binding.get("reference_image_ids"))
    expected_ids: list[str] = []
    if include_style_anchor and "style_anchor" in index:
        expected_ids.append("style_anchor")
    expected_ids.extend(storyboard_ids)

    for character_id in _character_ids(contract, design_segment):
        if character_id in index:
            expected_ids.append(character_id)
        anchor_id = f"char_{character_id}_anchor"
        if anchor_id in index:
            expected_ids.append(anchor_id)

    scene_id = binding.get("scene_ref") or design_segment.get("location_id")
    if scene_id:
        if scene_id in index:
            expected_ids.append(str(scene_id))
        scene_mood_id = f"scene_{scene_id}_mood"
        if scene_mood_id in index:
            expected_ids.append(scene_mood_id)

    expected_ids = _dedupe_text(expected_ids)
    resolved, missing = resolve_reference_ids(expected_ids, index)
    return {
        "storyboard_reference_image_ids": storyboard_ids,
        "expected_reference_ids": expected_ids,
        "resolved_references": resolved,
        "missing_reference_ids": missing,
    }


def resolve_reference_ids(
    reference_ids: list[str],
    index: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[str]]:
    resolved: list[dict[str, Any]] = []
    missing: list[str] = []
    seen_assets: set[str] = set()
    for ref_id in reference_ids:
        assets = index.get(ref_id) or []
        usable = [asset for asset in assets if asset.get("exists") or asset.get("url")]
        if not usable:
            missing.append(ref_id)
            continue
        for asset in usable:
            key = asset.get("url") or asset.get("path")
            if not key or key in seen_assets:
                continue
            item = dict(asset)
            item["requested_id"] = ref_id
            resolved.append(item)
            seen_assets.add(key)
    return resolved, _dedupe_text(missing)


def _index_character(
    index: dict[str, list[dict[str, Any]]],
    project_dir: Path,
    character: dict[str, Any],
    *,
    source: str,
) -> None:
    char_id = character.get("char_id")
    primary = character.get("primary_reference_path") or character.get("reference_image_url")
    primary_aliases = [
        value for value in [char_id, f"char_{char_id}_anchor" if char_id else ""] if value
    ]
    _add_reference(index, project_dir, primary_aliases, primary, role="character", source=source)

    image_fields = [
        "anchor_image",
        "turn_images",
        "expression_images",
        "dynamic_images",
        "outfit_images",
    ]
    for field in image_fields:
        value = character.get(field)
        images = value if isinstance(value, list) else ([value] if isinstance(value, dict) else [])
        for image in images:
            image_id = image.get("image_id")
            image_ref = image.get("url") or image.get("local_path")
            aliases = [alias for alias in [image_id] if alias]
            _add_reference(index, project_dir, aliases, image_ref, role="character", source=source)


def _index_environment(
    index: dict[str, list[dict[str, Any]]],
    project_dir: Path,
    environment: dict[str, Any],
    *,
    source: str,
) -> None:
    scene_id = environment.get("scene_id")
    primary = environment.get("primary_reference_path")
    primary_aliases = [
        value for value in [scene_id, f"scene_{scene_id}_mood" if scene_id else ""] if value
    ]
    _add_reference(index, project_dir, primary_aliases, primary, role="scene", source=source)

    for field in ("mood_images", "landmark_images", "detail_images"):
        for image in environment.get(field, []) or []:
            image_id = image.get("image_id")
            image_ref = image.get("url") or image.get("local_path")
            aliases = [alias for alias in [image_id] if alias]
            if image_id and scene_id and str(image_id).startswith(f"scene_{scene_id}_"):
                aliases.append(str(image_id).replace(f"scene_{scene_id}_", f"{scene_id}_", 1))
            _add_reference(index, project_dir, aliases, image_ref, role="scene", source=source)


def _add_reference(
    index: dict[str, list[dict[str, Any]]],
    project_dir: Path,
    aliases: list[str],
    value: Any,
    *,
    role: str,
    source: str,
) -> None:
    if not value:
        return
    text = str(value)
    path = ""
    url = ""
    exists = False
    if is_reference_uri(text):
        url = text
        exists = True
    else:
        local_path = Path(text)
        if not local_path.is_absolute():
            local_path = project_dir / local_path
        path = local_path.as_posix()
        exists = local_path.exists()

    alias_values = _dedupe_text(
        [*aliases, Path(text).stem if text and not is_reference_uri(text) else ""]
    )
    if not alias_values:
        return
    asset = {
        "asset_id": alias_values[0],
        "role": role,
        "source": source,
        "path": path,
        "url": url,
        "exists": exists,
    }
    for alias in alias_values:
        bucket = index.setdefault(alias, [])
        key = url or path
        if key and all((item.get("url") or item.get("path")) != key for item in bucket):
            bucket.append(asset)


def _character_ids(contract: dict[str, Any], design_segment: dict[str, Any]) -> list[str]:
    continuity = contract.get("continuity_constraints", {}) if contract else {}
    values = []
    values.extend(_as_list(continuity.get("characters")))
    values.extend(_as_list(design_segment.get("character_ids")))
    values.extend(_as_list(design_segment.get("character_refs")))
    return _dedupe_text(values)


def _infer_role(ref_id: str) -> str:
    if ref_id == "style_anchor" or ref_id.startswith("style_"):
        return "style"
    if ref_id.startswith("char_"):
        return "character"
    if ref_id.startswith("scene_"):
        return "scene"
    return "reference"


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, tuple):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        return [value] if value else []
    return [str(value)]


def _dedupe_text(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value) if value is not None else ""
        if text and text not in result:
            result.append(text)
    return result
