from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from narrascape.artifacts import validate_artifact
from narrascape.reference_assets import resolve_reference_assets_for_shot
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.ffmpeg import run_ffmpeg_raw


class VisualSemanticQAStage(Stage):
    """Check whether visuals match the script, characters, scene, and shot intent."""

    name = "visual_semantic_qa"
    depends_on = ["qa"]

    def __init__(self, llm_client: Any = None):
        self.llm_client = llm_client

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        timeline = context.config.project_dir / "film_timeline.yaml"
        if not timeline.exists():
            return False, f"film_timeline.yaml not found: {timeline}"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        output = config.pipeline_dir / "visual_semantic_report.yaml"
        output.parent.mkdir(parents=True, exist_ok=True)
        timeline = self._load_yaml(config.project_dir / "film_timeline.yaml")
        design = self._load_yaml(
            self._first_existing(
                config.project_dir / "design_report.yaml",
                config.pipeline_dir / "design_report.yaml",
            )
        )
        continuity = self._load_yaml(config.pipeline_dir / "continuity_bible.yaml")
        render_report = self._load_yaml(config.pipeline_dir / "render_report.yaml")
        director_contract = self._load_yaml(config.pipeline_dir / "director_contract.yaml")
        video_state = self._load_json(config.pipeline_dir / "video_gen_state.json")
        pre_production = self._load_yaml(config.pipeline_dir / "pre_production.yaml")
        visual_evidence = self._visual_clip_evidence(
            timeline,
            context,
            design,
            director_contract,
            video_state,
            pre_production,
        )
        deterministic_findings = self._reference_execution_findings(visual_evidence)

        llm_status = "not_configured"
        llm_error = ""
        if self.llm_client:
            try:
                result = self._ask_llm(
                    timeline,
                    design,
                    continuity,
                    render_report,
                    director_contract,
                    visual_evidence,
                    context,
                )
                findings = deterministic_findings + list(result.get("findings", []) or [])
                status = "needs_rework" if findings else result.get("status", "approved")
                llm_status = "used"
            except Exception as exc:
                findings = deterministic_findings + self._fallback_findings(
                    timeline, design, director_contract
                )
                status = "needs_rework" if findings else "approved"
                llm_status = "fallback_after_error"
                llm_error = str(exc)
        else:
            findings = deterministic_findings + self._fallback_findings(
                timeline, design, director_contract
            )
            status = "needs_rework" if findings else "approved"

        report = {
            "schema_version": "visual_semantic_report.v1",
            "project": {"name": config.project.name, "title": config.project.title},
            "status": status,
            "review_process": {
                "mode": (
                    "llm_visual_semantic_review" if llm_status == "used" else "metadata_fallback"
                ),
                "llm_status": llm_status,
                "llm_error": llm_error,
            },
            "reference_checks": visual_evidence,
            "findings": findings,
        }
        validate_artifact("visual_semantic_report", report)
        output.write_text(yaml.safe_dump(report, sort_keys=False), encoding="utf-8")
        return StageResult(
            self.name,
            True,
            outputs=[output],
            message=f"{len(findings)} visual semantic finding(s)",
            metadata={"status": status, "finding_count": len(findings)},
        )

    def _ask_llm(
        self,
        timeline: dict[str, Any],
        design: dict[str, Any],
        continuity: dict[str, Any],
        render_report: dict[str, Any],
        director_contract: dict[str, Any],
        visual_evidence: list[dict[str, Any]],
        context: StageContext,
    ) -> dict[str, Any]:
        payload = {
            "script": [segment.model_dump() for segment in context.script.segments],
            "visual_clips": visual_evidence,
            "design_segments": design.get("segments", []),
            "director_contract": director_contract,
            "continuity_risks": continuity.get("continuity_risks", []),
            "qa_checks": render_report.get("checks", {}),
        }
        prompt = (
            "You are a visual semantic QA director. "
            "Check whether each visual clip matches the narration, character identity, costume, location, "
            "shot intent, storyboard binding, reference images, and continuity bible. "
            "For each generated video or source footage clip, compare extracted frame paths against the "
            "style, character, and scene reference image paths. Flag identity drift, wardrobe drift, "
            "scene mismatch, style mismatch, and composition mismatch. Use provided file paths as evidence handles. "
            "Return only JSON.\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}\n\n"
            'Return JSON only: {"status":"approved|needs_rework","findings":[{"segment_id":1,"risk_type":"...","severity":"low|medium|high","evidence":"..."}]}.'
        )
        response = self.llm_client.complete(prompt, json_mode=True)
        if hasattr(response, "extract_json_safe"):
            data = response.extract_json_safe(default={})
        else:
            data = json.loads(getattr(response, "content", "{}"))
        if not isinstance(data, dict):
            raise ValueError("LLM returned non-object JSON")
        return data

    def _fallback_findings(
        self,
        timeline: dict[str, Any],
        design: dict[str, Any],
        director_contract: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        design_by_segment = {
            int(item.get("segment_id")): item
            for item in design.get("segments", [])
            if item.get("segment_id") is not None
        }
        contract_by_segment = {
            int(item.get("segment_id")): item
            for item in (director_contract or {}).get("shots", [])
            if item.get("segment_id") is not None
        }
        findings: list[dict[str, Any]] = []
        for clip in timeline.get("tracks", {}).get("visual", []) or []:
            if clip.get("segment_id") is None:
                continue
            segment_id = int(clip["segment_id"])
            design_item = design_by_segment.get(segment_id, {})
            metadata = (
                design_item.get("metadata", {})
                if isinstance(design_item.get("metadata"), dict)
                else {}
            )
            expected_location = design_item.get("location_id")
            expected_wardrobe = metadata.get("wardrobe")
            if (
                expected_location
                and clip.get("location_id")
                and expected_location != clip.get("location_id")
            ):
                findings.append(
                    {
                        "segment_id": segment_id,
                        "risk_type": "scene_mismatch",
                        "severity": "high",
                        "evidence": f"timeline location {clip.get('location_id')} differs from design {expected_location}",
                    }
                )
            if (
                expected_wardrobe
                and clip.get("wardrobe")
                and expected_wardrobe != clip.get("wardrobe")
            ):
                findings.append(
                    {
                        "segment_id": segment_id,
                        "risk_type": "wardrobe_mismatch",
                        "severity": "high",
                        "evidence": f"timeline wardrobe {clip.get('wardrobe')} differs from design {expected_wardrobe}",
                    }
                )
            contract = contract_by_segment.get(segment_id, {})
            findings.extend(self._contract_findings(segment_id, clip, contract))
            findings.extend(self._storyboard_binding_findings(segment_id, clip, contract))
        return findings

    def _reference_execution_findings(
        self, visual_evidence: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for clip in visual_evidence:
            segment_id = clip.get("segment_id")
            if segment_id is None:
                continue
            reference_assets = list(clip.get("reference_assets") or [])
            expected_ids = list(clip.get("expected_reference_ids") or [])
            missing_ids = list(clip.get("missing_reference_ids") or [])
            executed = clip.get("executed_reference_input") or {}
            if missing_ids:
                findings.append(
                    {
                        "segment_id": segment_id,
                        "risk_type": "reference_asset_missing",
                        "severity": "high",
                        "evidence": f"reference ids could not be resolved: {', '.join(missing_ids)}",
                    }
                )
            if expected_ids and clip.get("source") == "generated_video":
                executed_ids = set(executed.get("expected_reference_ids") or [])
                missing_from_execution = [
                    ref_id for ref_id in expected_ids if ref_id not in executed_ids
                ]
                uploaded_count = int(executed.get("uploaded_reference_count") or 0)
                if not executed:
                    findings.append(
                        {
                            "segment_id": segment_id,
                            "risk_type": "reference_images_not_executed",
                            "severity": "high",
                            "evidence": "generated video has reference requirements but no generate_video reference input record",
                        }
                    )
                elif uploaded_count == 0 and reference_assets:
                    findings.append(
                        {
                            "segment_id": segment_id,
                            "risk_type": "reference_images_not_executed",
                            "severity": "high",
                            "evidence": "reference assets resolved but generate_video uploaded zero reference images",
                        }
                    )
                elif missing_from_execution:
                    findings.append(
                        {
                            "segment_id": segment_id,
                            "risk_type": "reference_execution_mismatch",
                            "severity": "medium",
                            "evidence": f"generate_video did not record expected ids: {', '.join(missing_from_execution)}",
                        }
                    )
            if (
                reference_assets
                and clip.get("source") in {"generated_video", "source_media"}
                and clip.get("exists")
                and not clip.get("extracted_frames")
            ):
                findings.append(
                    {
                        "segment_id": segment_id,
                        "risk_type": "visual_frame_extract_failed",
                        "severity": "medium",
                        "evidence": "reference comparison requires extracted video frames, but no frame was produced",
                    }
                )
        return findings

    def _contract_findings(
        self,
        segment_id: int,
        clip: dict[str, Any],
        contract: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not contract:
            return []
        fields = self._clip_semantic_tokens(clip)
        findings: list[dict[str, Any]] = []
        for value in contract.get("qa", {}).get("must_show", []) or []:
            if not value:
                continue
            if str(value).lower() not in fields:
                findings.append(
                    {
                        "segment_id": segment_id,
                        "risk_type": "contract_must_show_missing",
                        "severity": "high",
                        "evidence": f"contract requires {value!r}, but timeline metadata does not contain it",
                    }
                )
        for value in contract.get("qa", {}).get("must_not_show", []) or []:
            if not value:
                continue
            if str(value).lower() in fields:
                findings.append(
                    {
                        "segment_id": segment_id,
                        "risk_type": "contract_must_not_show_present",
                        "severity": "high",
                        "evidence": f"contract forbids {value!r}, but timeline metadata contains it",
                    }
                )
        return findings

    def _storyboard_binding_findings(
        self,
        segment_id: int,
        clip: dict[str, Any],
        contract: dict[str, Any],
    ) -> list[dict[str, Any]]:
        binding = contract.get("storyboard_binding", {}) if contract else {}
        if not binding:
            return []
        findings: list[dict[str, Any]] = []
        expected_scene = binding.get("scene_ref")
        if (
            expected_scene
            and clip.get("location_id")
            and str(clip.get("location_id")) != str(expected_scene)
        ):
            findings.append(
                {
                    "segment_id": segment_id,
                    "risk_type": "storyboard_scene_mismatch",
                    "severity": "high",
                    "evidence": f"timeline location {clip.get('location_id')} differs from storyboard scene {expected_scene}",
                }
            )
        expected_wardrobe = binding.get("wardrobe_lock")
        if (
            expected_wardrobe
            and clip.get("wardrobe")
            and str(clip.get("wardrobe")) != str(expected_wardrobe)
        ):
            findings.append(
                {
                    "segment_id": segment_id,
                    "risk_type": "storyboard_wardrobe_mismatch",
                    "severity": "high",
                    "evidence": f"timeline wardrobe {clip.get('wardrobe')} differs from storyboard wardrobe lock {expected_wardrobe}",
                }
            )
        expected_positions = list(binding.get("character_positions") or [])
        actual_positions = list(clip.get("character_positions") or [])
        if (
            expected_positions
            and actual_positions
            and not self._positions_match(expected_positions, actual_positions)
        ):
            findings.append(
                {
                    "segment_id": segment_id,
                    "risk_type": "storyboard_character_position_mismatch",
                    "severity": "medium",
                    "evidence": "timeline character positions do not match storyboard binding",
                }
            )
        expected_composition = list(binding.get("composition_requirements") or [])
        actual_composition = clip.get("composition")
        if (
            expected_composition
            and actual_composition
            and not self._any_text_overlap(expected_composition, [actual_composition])
        ):
            findings.append(
                {
                    "segment_id": segment_id,
                    "risk_type": "storyboard_composition_mismatch",
                    "severity": "medium",
                    "evidence": "timeline composition does not match storyboard binding",
                }
            )
        return findings

    def _positions_match(self, expected: list[Any], actual: list[Any]) -> bool:
        actual_cues = self._position_cues(" ".join(str(item) for item in actual))
        expected_cue_groups = [
            cues for cues in (self._position_cues(str(item)) for item in expected) if cues
        ]
        if expected_cue_groups:
            return any(cues <= actual_cues for cues in expected_cue_groups)

        actual_tokens = self._semantic_words(" ".join(str(item) for item in actual))
        for item in expected:
            expected_tokens = self._semantic_words(str(item))
            if expected_tokens and len(expected_tokens & actual_tokens) >= min(
                3, len(expected_tokens)
            ):
                return True
        return False

    def _position_cues(self, text: str) -> set[str]:
        import re

        cue_words = {
            "left",
            "right",
            "center",
            "centre",
            "center-left",
            "center-right",
            "foreground",
            "background",
            "edge",
            "middle",
            "window",
            "silhouette",
            "profile",
            "overhead",
            "low-angle",
            "high-angle",
            "behind",
            "front",
            "back",
            "near",
            "far",
            "toward",
            "towards",
            "away",
        }
        words = set(re.findall(r"[a-zA-Z0-9_-]+", text.lower()))
        cues = {word for word in words if word in cue_words}
        if "center" in words and "left" in words:
            cues.add("center-left")
        if "center" in words and "right" in words:
            cues.add("center-right")
        return cues

    def _any_text_overlap(self, expected: list[Any], actual: list[Any]) -> bool:
        actual_tokens = self._semantic_words(" ".join(str(item) for item in actual))
        if not actual_tokens:
            return False
        for item in expected:
            expected_tokens = self._semantic_words(str(item))
            if expected_tokens and expected_tokens & actual_tokens:
                return True
        return False

    def _semantic_words(self, text: str) -> set[str]:
        import re

        stopwords = {
            "the",
            "and",
            "with",
            "into",
            "toward",
            "towards",
            "beside",
            "against",
            "this",
            "that",
            "from",
            "frame",
            "shot",
            "camera",
            "composition",
        }
        return {
            word
            for word in re.findall(r"[a-zA-Z0-9_-]+", text.lower())
            if len(word) > 3 and word not in stopwords
        }

    def _clip_semantic_tokens(self, clip: dict[str, Any]) -> str:
        values: list[str] = []
        for key in (
            "location_id",
            "wardrobe",
            "lighting_scheme",
            "shot_type",
            "movement",
            "composition",
        ):
            if clip.get(key):
                values.append(str(clip[key]))
        for key in ("character_ids", "character_positions", "storyboard_frame_ids"):
            values.extend(str(item) for item in clip.get(key, []) or [])
        return " ".join(values).lower()

    def _visual_clips_with_paths(
        self, timeline: dict[str, Any], context: StageContext
    ) -> list[dict[str, Any]]:
        clips = []
        for clip in timeline.get("tracks", {}).get("visual", []) or []:
            item = dict(clip)
            rel = item.get("path")
            item["exists"] = bool(rel and (context.config.project_dir / rel).exists())
            clips.append(item)
        return clips

    def _visual_clip_evidence(
        self,
        timeline: dict[str, Any],
        context: StageContext,
        design: dict[str, Any],
        director_contract: dict[str, Any],
        video_state: dict[str, Any],
        pre_production: dict[str, Any],
    ) -> list[dict[str, Any]]:
        design_by_segment = {
            int(item.get("segment_id")): item
            for item in design.get("segments", []) or []
            if item.get("segment_id") is not None
        }
        contract_by_segment = {
            int(item.get("segment_id")): item
            for item in director_contract.get("shots", []) or []
            if item.get("segment_id") is not None
        }
        evidence: list[dict[str, Any]] = []
        for clip in timeline.get("tracks", {}).get("visual", []) or []:
            item = dict(clip)
            rel = item.get("path")
            path = context.config.project_dir / rel if rel else None
            item["exists"] = bool(path and path.exists())
            if path and path.exists():
                item["absolute_path"] = path.as_posix()
            segment_id = item.get("segment_id")
            if segment_id is not None:
                try:
                    segment_id_int = int(segment_id)
                except (TypeError, ValueError):
                    segment_id_int = None
                if segment_id_int is not None:
                    contract = contract_by_segment.get(segment_id_int, {})
                    design_segment = design_by_segment.get(segment_id_int, {})
                    reference_manifest = resolve_reference_assets_for_shot(
                        context.config.project_dir,
                        contract=contract,
                        design_segment=design_segment,
                        pre_production=pre_production,
                        design=design,
                    )
                    item["storyboard_reference_image_ids"] = reference_manifest[
                        "storyboard_reference_image_ids"
                    ]
                    item["expected_reference_ids"] = reference_manifest["expected_reference_ids"]
                    item["missing_reference_ids"] = reference_manifest["missing_reference_ids"]
                    item["reference_assets"] = [
                        self._compact_reference_asset(asset)
                        for asset in reference_manifest["resolved_references"]
                    ]
                    item["executed_reference_input"] = video_state.get("reference_inputs", {}).get(
                        f"vid_{segment_id_int:02d}", {}
                    )
            item["extracted_frames"] = self._extract_clip_frames(item, path, context)
            evidence.append(item)
        return evidence

    def _extract_clip_frames(
        self,
        clip: dict[str, Any],
        path: Path | None,
        context: StageContext,
    ) -> list[str]:
        if not path or not path.exists():
            return []
        if clip.get("source") == "generated_image":
            return [path.as_posix()]
        if clip.get("source") not in {"generated_video", "source_media"}:
            return []
        segment_id = clip.get("segment_id")
        if segment_id is None:
            return []
        out_dir = context.config.pipeline_dir / "visual_semantic_frames"
        out_dir.mkdir(parents=True, exist_ok=True)
        output = out_dir / f"segment_{int(segment_id):03d}_frame_001.jpg"
        try:
            result = run_ffmpeg_raw(
                [
                    "-ss",
                    "0.5",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(output),
                ],
                timeout=30,
            )
        except Exception:
            return []
        if result.returncode == 0 and output.exists() and output.stat().st_size > 0:
            return [output.as_posix()]
        return []

    def _compact_reference_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        item = {
            "requested_id": asset.get("requested_id"),
            "asset_id": asset.get("asset_id"),
            "role": asset.get("role"),
            "source": asset.get("source"),
            "path": asset.get("path"),
            "exists": asset.get("exists"),
        }
        url = str(asset.get("url") or "")
        if url.startswith("data:"):
            item["url"] = "data-uri"
        elif url:
            item["url"] = url
        return item

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _first_existing(self, *paths: Path) -> Path:
        for path in paths:
            if path.exists():
                return path
        return paths[0]
