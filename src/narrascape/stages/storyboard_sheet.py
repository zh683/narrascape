from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from narrascape.artifacts import validate_artifact
from narrascape.reference_assets import build_reference_index, resolve_reference_ids
from narrascape.stages.base import Stage, StageContext, StageResult
from narrascape.utils.safe_io import atomic_promote_file, atomic_write_yaml, load_yaml_mapping


class StoryboardSheetStage(Stage):
    """Render a product-style storyboard contact sheet and PDF review board."""

    name = "storyboard_sheet"
    depends_on = ["reference_plate", "generate_images"]
    outputs = [
        "pipeline/{name}/storyboard_sheet.yaml",
        "pipeline/{name}/storyboard_sheet.png",
        "pipeline/{name}/storyboard_sheet.pdf",
    ]

    def can_run(self, context: StageContext) -> tuple[bool, str]:
        config = context.config
        sources = [
            config.pipeline_dir / "pre_production.yaml",
            config.pipeline_dir / "director_contract.yaml",
            config.pipeline_dir / "reference_plates.yaml",
        ]
        if not any(path.exists() for path in sources):
            return False, "No storyboard source artifacts found"
        return True, ""

    def run(self, context: StageContext) -> StageResult:
        config = context.config
        project_dir = config.project_dir
        pipe_dir = config.pipeline_dir
        pipe_dir.mkdir(parents=True, exist_ok=True)

        pre_production = self._load_yaml(pipe_dir / "pre_production.yaml")
        director_contract = self._load_yaml(pipe_dir / "director_contract.yaml")
        reference_plates = self._load_yaml(pipe_dir / "reference_plates.yaml")
        design_report = self._load_yaml(pipe_dir / "design_report.yaml")
        image_map = load_yaml_mapping(project_dir / "image_map.yaml")

        reference_index = build_reference_index(
            project_dir, pre_production=pre_production, design=design_report
        )
        frames = self._storyboard_frames(pre_production, director_contract, reference_plates)
        if not frames:
            frames = [self._placeholder_frame()]

        shots_by_segment = self._shots_by_segment(director_contract)
        shots_by_frame_id = self._shots_by_frame_id(director_contract)
        plates_by_segment = self._plates_by_segment(reference_plates)
        image_map_by_segment = self._image_map_by_segment(image_map)

        cards: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        for order, frame in enumerate(frames, start=1):
            card, card_findings = self._build_card(
                order=order,
                frame=frame,
                project_dir=project_dir,
                reference_index=reference_index,
                shots_by_segment=shots_by_segment,
                shots_by_frame_id=shots_by_frame_id,
                plates_by_segment=plates_by_segment,
                image_map_by_segment=image_map_by_segment,
            )
            cards.append(card)
            findings.extend(card_findings)

        pages = self._paginate(cards, cards_per_page=12)
        page_images = [
            self._render_page(
                page_index=index + 1,
                total_pages=len(pages),
                page_cards=page_cards,
                project_dir=project_dir,
                project_title=config.project.title,
                project_name=config.project.name,
                page_card_count=len(page_cards),
                status="degraded" if findings else "ready",
            )
            for index, page_cards in enumerate(pages)
        ]

        if not page_images:
            page_images = [
                self._render_page(
                    page_index=1,
                    total_pages=1,
                    page_cards=[],
                    project_dir=project_dir,
                    project_title=config.project.title,
                    project_name=config.project.name,
                    page_card_count=0,
                    status="degraded",
                )
            ]

        report_status = "degraded" if findings else "ready"
        report = {
            "schema_version": "storyboard_sheet.v1",
            "status": report_status,
            "project": {
                "name": config.project.name,
                "title": config.project.title,
            },
            "shot_count": len(cards),
            "page_count": len(page_images),
            "render": {
                "width": page_images[0].width,
                "height": page_images[0].height,
                "columns": 4,
                "rows": 3,
                "png_path": str((pipe_dir / "storyboard_sheet.png").relative_to(project_dir)),
                "pdf_path": str((pipe_dir / "storyboard_sheet.pdf").relative_to(project_dir)),
                "preview_page_index": 1,
            },
            "pages": [
                {
                    "page_index": index + 1,
                    "card_count": len(page_cards),
                    "cards": page_cards,
                }
                for index, page_cards in enumerate(pages)
            ],
            "findings": findings,
        }

        validate_artifact("storyboard_sheet", report)
        yaml_path = pipe_dir / "storyboard_sheet.yaml"
        png_path = pipe_dir / "storyboard_sheet.png"
        pdf_path = pipe_dir / "storyboard_sheet.pdf"
        atomic_write_yaml(yaml_path, report)
        self._save_page_image(page_images[0], png_path)
        self._save_pdf(page_images, pdf_path)

        return StageResult(
            self.name,
            True,
            outputs=[yaml_path, png_path, pdf_path],
            message=f"{len(cards)} storyboard card(s) across {len(page_images)} page(s)",
            metadata={
                "status": report_status,
                "shot_count": len(cards),
                "page_count": len(page_images),
                "finding_count": len(findings),
            },
        )

    def _storyboard_frames(
        self,
        pre_production: dict[str, Any],
        director_contract: dict[str, Any],
        reference_plates: dict[str, Any],
    ) -> list[dict[str, Any]]:
        frames = list((pre_production.get("storyboard", {}) or {}).get("frames", []) or [])
        if frames:
            frames.sort(
                key=lambda item: (
                    int(item.get("segment_id") or 0),
                    int(item.get("frame_index") or 0),
                    str(item.get("frame_id") or ""),
                )
            )
            return frames

        synthesized: list[dict[str, Any]] = []
        plates_by_segment = self._plates_by_segment(reference_plates)
        for shot in director_contract.get("shots", []) or []:
            try:
                segment_id = int(shot.get("segment_id"))
            except (TypeError, ValueError):
                continue
            binding = shot.get("storyboard_binding", {}) if isinstance(shot, dict) else {}
            frame_ids = list(binding.get("storyboard_frame_ids") or []) or [
                f"sb_{segment_id:02d}_01"
            ]
            plate = plates_by_segment.get(segment_id, {})
            for index, frame_id in enumerate(frame_ids):
                synthesized.append(
                    {
                        "frame_id": frame_id,
                        "segment_id": segment_id,
                        "frame_index": index,
                        "description": str(
                            shot.get("story_reason")
                            or shot.get("description")
                            or shot.get("video_prompt")
                            or ""
                        ),
                        "shot_type": str(
                            shot.get("shot_type") or plate.get("shot_type") or "medium"
                        ),
                        "camera_movement": str(
                            shot.get("camera_movement") or plate.get("camera_movement") or "still"
                        ),
                        "camera_angle": str(
                            shot.get("camera_angle") or plate.get("camera_angle") or "eye-level"
                        ),
                        "character_positions": list(
                            binding.get("character_positions")
                            or plate.get("character_positions")
                            or []
                        ),
                        "emotion": str(shot.get("emotion") or "neutral"),
                        "duration_hint": float(shot.get("duration_hint") or 3.0),
                        "character_refs": list(
                            binding.get("character_refs") or plate.get("character_refs") or []
                        ),
                        "scene_ref": str(binding.get("scene_ref") or plate.get("scene_ref") or ""),
                        "reference_image_ids": list(
                            binding.get("reference_image_ids")
                            or plate.get("storyboard_reference_image_ids")
                            or []
                        ),
                        "notes": str(shot.get("story_reason") or ""),
                    }
                )
        synthesized.sort(
            key=lambda item: (
                int(item.get("segment_id") or 0),
                int(item.get("frame_index") or 0),
                str(item.get("frame_id") or ""),
            )
        )
        return synthesized

    def _build_card(
        self,
        *,
        order: int,
        frame: dict[str, Any],
        project_dir: Path,
        reference_index: dict[str, list[dict[str, Any]]],
        shots_by_segment: dict[int, dict[str, Any]],
        shots_by_frame_id: dict[str, dict[str, Any]],
        plates_by_segment: dict[int, dict[str, Any]],
        image_map_by_segment: dict[int, list[str]],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        findings: list[dict[str, Any]] = []
        segment_id = self._as_int(frame.get("segment_id"))
        frame_id = str(frame.get("frame_id") or f"sb_{segment_id:02d}_01")
        shot = shots_by_frame_id.get(frame_id) or shots_by_segment.get(segment_id, {})
        binding = shot.get("storyboard_binding", {}) if isinstance(shot, dict) else {}
        plate = plates_by_segment.get(segment_id, {})
        reference_ids = self._dedupe_text(
            [
                *self._as_list(frame.get("reference_image_ids")),
                *self._as_list(binding.get("reference_image_ids")),
                *self._as_list(plate.get("storyboard_reference_image_ids")),
                *image_map_by_segment.get(segment_id, []),
            ]
        )
        preview = self._resolve_preview_source(
            project_dir=project_dir,
            candidate_ids=reference_ids,
            plate=plate,
            reference_index=reference_index,
        )
        if preview["kind"] == "placeholder":
            findings.append(
                {
                    "frame_id": frame_id,
                    "segment_id": segment_id,
                    "risk_type": "storyboard_preview_missing",
                    "severity": "medium",
                    "evidence": f"no local preview image for {frame_id}",
                }
            )

        missing_ids = [
            str(item) for item in self._as_list(plate.get("missing_reference_ids")) if str(item)
        ]
        if missing_ids:
            findings.append(
                {
                    "frame_id": frame_id,
                    "segment_id": segment_id,
                    "risk_type": "storyboard_reference_missing",
                    "severity": "medium",
                    "evidence": f"missing storyboard reference id(s): {', '.join(missing_ids)}",
                }
            )

        character_positions = self._dedupe_text(
            [
                *self._as_list(frame.get("character_positions")),
                *self._as_list(binding.get("character_positions")),
                *self._as_list(plate.get("character_positions")),
            ]
        )
        composition_requirements = self._dedupe_text(
            [
                *self._as_list(binding.get("composition_requirements")),
                *self._as_list(plate.get("composition_requirements")),
            ]
        )
        wardrobe_lock = str(
            binding.get("wardrobe_lock") or plate.get("wardrobe_lock") or ""
        ).strip()
        scene_ref = str(
            frame.get("scene_ref") or binding.get("scene_ref") or plate.get("scene_ref") or ""
        )
        shot_type = str(frame.get("shot_type") or binding.get("shot_type") or "medium")
        description = str(
            frame.get("description") or shot.get("story_reason") or shot.get("video_prompt") or ""
        ).strip()
        notes = str(frame.get("notes") or shot.get("story_reason") or "").strip()
        duration = float(frame.get("duration_hint") or shot.get("duration_hint") or 3.0)

        summary_lines = [
            f"scene: {scene_ref or '—'}",
            f"wardrobe: {wardrobe_lock or '—'}",
            f"refs: {', '.join(reference_ids[:3]) if reference_ids else '—'}",
        ]

        card = {
            "order": order,
            "frame_id": frame_id,
            "frame_ids": [frame_id],
            "segment_id": segment_id,
            "shot_id": str(shot.get("shot_id") or ""),
            "shot_type": shot_type,
            "camera_movement": str(
                frame.get("camera_movement") or binding.get("camera_movement") or ""
            ),
            "camera_angle": str(frame.get("camera_angle") or binding.get("camera_angle") or ""),
            "description": description,
            "notes": notes,
            "duration_hint": round(duration, 3),
            "emotion": str(frame.get("emotion") or shot.get("emotion") or ""),
            "scene_ref": scene_ref,
            "character_positions": character_positions,
            "wardrobe_lock": wardrobe_lock,
            "composition_requirements": composition_requirements,
            "reference_image_ids": reference_ids,
            "preview_source_kind": preview["kind"],
            "preview_source_id": preview["id"],
            "preview_source_path": preview["path"],
            "preview_status": preview["status"],
            "summary_lines": summary_lines,
        }
        return card, findings

    def _resolve_preview_source(
        self,
        *,
        project_dir: Path,
        candidate_ids: list[str],
        plate: dict[str, Any],
        reference_index: dict[str, list[dict[str, Any]]],
    ) -> dict[str, str]:
        plate_assets = plate.get("reference_assets", []) if isinstance(plate, dict) else []
        for asset in plate_assets or []:
            resolved = self._asset_path(project_dir, asset.get("path") or "")
            if resolved and resolved.exists():
                return {
                    "kind": self._kind_for_path(resolved),
                    "id": str(asset.get("asset_id") or asset.get("requested_id") or resolved.stem),
                    "path": self._display_path(project_dir, resolved),
                    "status": "resolved",
                }

        for candidate_id in candidate_ids:
            generated = project_dir / "assets" / "images" / f"{candidate_id}.png"
            if generated.exists():
                return {
                    "kind": "generated_image",
                    "id": candidate_id,
                    "path": self._display_path(project_dir, generated),
                    "status": "resolved",
                }

            reference = self._reference_asset_from_id(project_dir, candidate_id, reference_index)
            if reference:
                return {
                    "kind": self._kind_for_path(reference),
                    "id": candidate_id,
                    "path": self._display_path(project_dir, reference),
                    "status": "resolved",
                }

        return {
            "kind": "placeholder",
            "id": "",
            "path": "",
            "status": "missing",
        }

    def _reference_asset_from_id(
        self,
        project_dir: Path,
        candidate_id: str,
        reference_index: dict[str, list[dict[str, Any]]],
    ) -> Path | None:
        asset = self._resolve_reference_asset(project_dir, candidate_id, reference_index)
        if asset is not None:
            return asset
        refs_dir = project_dir / "assets" / "references"
        for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            candidate = refs_dir / f"{candidate_id}{ext}"
            if candidate.exists():
                return candidate
        return None

    def _resolve_reference_asset(
        self,
        project_dir: Path,
        candidate_id: str,
        reference_index: dict[str, list[dict[str, Any]]],
    ) -> Path | None:
        resolved, _ = resolve_reference_ids([candidate_id], reference_index)
        for asset in resolved:
            path = self._asset_path(project_dir, asset.get("path") or "")
            if path is not None and path.exists():
                return path
        return None

    def _render_page(
        self,
        *,
        page_index: int,
        total_pages: int,
        page_cards: list[dict[str, Any]],
        project_dir: Path,
        project_title: str,
        project_name: str,
        page_card_count: int,
        status: str,
    ) -> Image.Image:
        width, height = 2400, 1700
        margin_x = 72
        margin_top = 72
        margin_bottom = 72
        header_height = 170
        gap = 20
        columns = 4
        rows = 3
        card_w = int((width - margin_x * 2 - gap * (columns - 1)) / columns)
        card_h = int(
            (height - margin_top - header_height - margin_bottom - gap * (rows - 1)) / rows
        )

        page = Image.new("RGB", (width, height), "#f5f1e8")
        draw = ImageDraw.Draw(page)
        self._draw_page_texture(page)
        title_font = self._load_font(66, bold=True)
        subtitle_font = self._load_font(24, bold=False)
        meta_font = self._load_font(20, bold=False)
        header_font = self._load_font(26, bold=True)
        tiny_font = self._load_font(16, bold=False)

        draw.text(
            (width // 2, 70),
            "故事板 / Storyboard",
            fill="#171717",
            font=title_font,
            anchor="ma",
        )
        subtitle = f"{project_title}  |  {project_name}"
        draw.text(
            (width // 2, 132),
            subtitle,
            fill="#45413b",
            font=subtitle_font,
            anchor="ma",
        )
        meta = f"cards {page_card_count}  |  page {page_index}/{total_pages}  |  status {status}"
        draw.text((width - 80, 70), meta, fill="#5e5a52", font=meta_font, anchor="ra")

        if not page_cards:
            body = self._load_font(28, bold=True)
            draw.rounded_rectangle(
                (margin_x, 260, width - margin_x, height - 120),
                radius=14,
                fill="#fbfaf7",
                outline="#c9c1b3",
                width=2,
            )
            draw.text(
                (width // 2, height // 2 - 18),
                "No storyboard frames available",
                fill="#44413c",
                font=body,
                anchor="ma",
            )
            draw.text(
                (width // 2, height // 2 + 24),
                "The sheet still renders so the pipeline stays reviewable.",
                fill="#6f685f",
                font=tiny_font,
                anchor="ma",
            )
            return page

        for index, card in enumerate(page_cards):
            col = index % columns
            row = index // columns
            x = margin_x + col * (card_w + gap)
            y = margin_top + header_height + row * (card_h + gap)
            self._draw_card(
                project_dir=project_dir,
                page=page,
                draw=draw,
                card=card,
                box=(x, y, x + card_w, y + card_h),
                header_font=header_font,
                subtitle_font=subtitle_font,
                meta_font=meta_font,
                tiny_font=tiny_font,
            )
        return page

    def _draw_card(
        self,
        *,
        project_dir: Path,
        page: Image.Image,
        draw: ImageDraw.ImageDraw,
        card: dict[str, Any],
        box: tuple[int, int, int, int],
        header_font: ImageFont.ImageFont,
        subtitle_font: ImageFont.ImageFont,
        meta_font: ImageFont.ImageFont,
        tiny_font: ImageFont.ImageFont,
    ) -> None:
        x0, y0, x1, y1 = box
        pad = 14
        draw.rectangle((x0, y0, x1, y1), fill="#fbfaf7", outline="#b9b1a4", width=2)

        title = f"{card['order']}. {card['frame_id']}"
        subtitle = f"{card['shot_type'].replace('_', ' ')}  |  segment {card['segment_id']}"
        draw.text((x0 + pad, y0 + 10), title, fill="#191919", font=header_font)
        draw.text((x0 + pad, y0 + 44), subtitle, fill="#5f5a53", font=subtitle_font)

        preview_top = y0 + 82
        preview_bottom = y0 + int((y1 - y0) * 0.66)
        preview_box = (x0 + pad, preview_top, x1 - pad, preview_bottom)
        self._draw_preview(project_dir, page, draw, preview_box, card)

        text_top = preview_bottom + 14
        description = card.get("description") or " "
        description_lines = self._wrap_text(
            draw,
            description,
            meta_font,
            max_width=(x1 - x0) - pad * 2,
            max_lines=2,
        )
        line_height = 21
        for line_index, line in enumerate(description_lines):
            draw.text(
                (x0 + pad, text_top + line_index * line_height),
                line,
                fill="#2b2926",
                font=meta_font,
            )

        footer_top = y1 - 58
        tag_font = self._load_font(15, bold=False)
        tags = [
            (f"scene: {card.get('scene_ref') or '—'}", "#2f6f61"),
            (f"wardrobe: {card.get('wardrobe_lock') or '—'}", "#3b82f6"),
            (
                f"refs: {', '.join(card.get('reference_image_ids', [])[:2]) or '—'}",
                "#d97706",
            ),
        ]
        cursor_x = x0 + pad
        for label, color in tags:
            label_width = int(draw.textlength(label, font=tag_font)) + 10
            if cursor_x + label_width > x1 - pad:
                break
            draw.text((cursor_x, footer_top), label, fill=color, font=tag_font)
            cursor_x += label_width + 16

        preview_kind = str(card.get("preview_source_kind") or "placeholder")
        badge_color = {
            "generated_image": "#166534",
            "reference_image": "#a16207",
            "placeholder": "#b91c1c",
        }.get(preview_kind, "#6b7280")
        badge_text = preview_kind.replace("_", " ")
        badge_width = int(draw.textlength(badge_text, font=tag_font)) + 12
        draw.rectangle(
            (x1 - pad - badge_width, footer_top - 2, x1 - pad, footer_top + 20),
            fill=badge_color,
        )
        draw.text(
            (x1 - pad - badge_width + 6, footer_top),
            badge_text,
            fill="#ffffff",
            font=tag_font,
        )

        status_text = "resolved" if preview_kind != "placeholder" else "placeholder"
        draw.text(
            (x0 + pad, y1 - 30),
            f"{status_text}  |  duration {card.get('duration_hint', 0):.1f}s",
            fill="#6b645b",
            font=tiny_font,
        )

    def _draw_preview(
        self,
        project_dir: Path,
        page: Image.Image,
        draw: ImageDraw.ImageDraw,
        box: tuple[int, int, int, int],
        card: dict[str, Any],
    ) -> None:
        x0, y0, x1, y1 = box
        preview_bg = Image.new("RGB", (x1 - x0, y1 - y0), "#e8e2d6")
        path_text = str(card.get("preview_source_path") or "")
        if path_text:
            path = self._asset_path(project_dir, path_text)
            if path is not None and path.exists():
                try:
                    with Image.open(path) as source:
                        preview = ImageOps.contain(
                            source.convert("RGB"),
                            (x1 - x0, y1 - y0),
                            method=Image.Resampling.LANCZOS,
                        )
                        offset = (
                            ((x1 - x0) - preview.width) // 2,
                            ((y1 - y0) - preview.height) // 2,
                        )
                        preview_bg.paste(preview, offset)
                except Exception:
                    self._draw_placeholder_preview(preview_bg, card)
            else:
                self._draw_placeholder_preview(preview_bg, card)
        else:
            self._draw_placeholder_preview(preview_bg, card)

        page.paste(preview_bg, (x0, y0))
        draw.rectangle((x0, y0, x1, y1), outline="#d7d0c4", width=1)
        preview_label = f"{card.get('preview_source_kind', 'placeholder')}  {card.get('preview_source_id') or ''}".strip()
        tag_font = self._load_font(14, bold=False)
        tag_w = int(draw.textlength(preview_label, font=tag_font)) + 12
        draw.rectangle((x0 + 8, y0 + 8, x0 + 8 + tag_w, y0 + 30), fill="#111827")
        draw.text((x0 + 14, y0 + 10), preview_label, fill="#ffffff", font=tag_font)

    def _draw_placeholder_preview(
        self,
        preview_bg: Image.Image,
        card: dict[str, Any],
    ) -> None:
        draw = ImageDraw.Draw(preview_bg)
        w, h = preview_bg.size
        draw.rectangle((0, 0, w - 1, h - 1), fill="#e5ded0", outline="#c5b9aa")
        draw.line((0, 0, w, h), fill="#c36b5f", width=4)
        draw.line((0, h, w, 0), fill="#c36b5f", width=4)
        title_font = self._load_font(22, bold=True)
        body_font = self._load_font(14, bold=False)
        draw.text((w // 2, h // 2 - 20), "NO PREVIEW", fill="#6b2a23", font=title_font, anchor="ma")
        detail = card.get("frame_id") or "missing frame"
        draw.text((w // 2, h // 2 + 14), detail, fill="#6b2a23", font=body_font, anchor="ma")

    def _save_page_image(self, page: Image.Image, path: Path) -> None:
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.save(tmp, format="PNG")
            atomic_promote_file(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def _save_pdf(self, pages: list[Image.Image], path: Path) -> None:
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        pdf_pages = [page.convert("RGB") for page in pages]
        try:
            pdf_pages[0].save(
                tmp,
                format="PDF",
                save_all=True,
                append_images=pdf_pages[1:],
                resolution=144.0,
            )
            atomic_promote_file(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def _paginate(
        self, cards: list[dict[str, Any]], *, cards_per_page: int
    ) -> list[list[dict[str, Any]]]:
        return [
            cards[index : index + cards_per_page] for index in range(0, len(cards), cards_per_page)
        ]

    def _draw_page_texture(self, page: Image.Image) -> None:
        try:
            noise = Image.effect_noise(page.size, 8).convert("L")
            overlay = Image.new("RGB", page.size, "#ffffff")
            overlay.putalpha(noise.point(lambda value: 14 if value > 0 else 0))
            page.paste(overlay.convert("RGB"), mask=overlay.split()[-1])
        except Exception:
            return

    def _load_font(self, size: int, *, bold: bool) -> ImageFont.ImageFont:
        candidates = [
            "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/simsun.ttc",
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
            "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        ]
        for candidate in candidates:
            try:
                return ImageFont.truetype(candidate, size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _wrap_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        *,
        max_width: int,
        max_lines: int,
    ) -> list[str]:
        normalized = " ".join(str(text).split())
        if not normalized:
            return []

        lines: list[str] = []
        current = ""
        for token in re.findall(r"\S+\s*|\s+", normalized):
            candidate = f"{current}{token}"
            if current and int(draw.textlength(candidate, font=font)) > max_width:
                lines.append(current.rstrip())
                current = token.lstrip()
                if int(draw.textlength(current, font=font)) > max_width:
                    for char in current:
                        candidate = f"{lines[-1] if lines else ''}{char}"
                        if (
                            lines
                            and int(draw.textlength(candidate, font=font)) > max_width
                            or not lines
                            and int(draw.textlength(char, font=font)) > max_width
                        ):
                            lines.append(char)
                        else:
                            if lines:
                                lines[-1] = candidate
                            else:
                                current = char
                    continue
            else:
                current = candidate
        if current:
            lines.append(current.rstrip())

        fixed: list[str] = []
        for line in lines:
            candidate = line.strip()
            if not candidate:
                continue
            if int(draw.textlength(candidate, font=font)) <= max_width:
                fixed.append(candidate)
                continue
            buffer = ""
            for char in candidate:
                if buffer and int(draw.textlength(buffer + char, font=font)) > max_width:
                    fixed.append(buffer)
                    buffer = char
                else:
                    buffer += char
            if buffer:
                fixed.append(buffer)

        if len(fixed) > max_lines:
            fixed = fixed[:max_lines]
            last = fixed[-1]
            while last and int(draw.textlength(last + "…", font=font)) > max_width:
                last = last[:-1]
            fixed[-1] = f"{last}…" if last else "…"
        return fixed

    def _asset_path(self, project_path: Path, raw: str) -> Path | None:
        if not raw:
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = project_path / path
        return path

    def _display_path(self, project_dir: Path, path: Path) -> str:
        try:
            return path.relative_to(project_dir).as_posix()
        except ValueError:
            return path.as_posix()

    def _kind_for_path(self, path: Path) -> str:
        parts = {part.lower() for part in path.parts}
        if "images" in parts:
            return "generated_image"
        if "references" in parts or "storyboard" in parts:
            return "reference_image"
        return "reference_image"

    def _storyboard_frame_id(self, frame: dict[str, Any]) -> str:
        return str(frame.get("frame_id") or "")

    def _placeholder_frame(self) -> dict[str, Any]:
        return {
            "frame_id": "sb_placeholder_01",
            "segment_id": 0,
            "frame_index": 0,
            "description": "No storyboard frames were available to render.",
            "shot_type": "medium",
            "camera_movement": "still",
            "camera_angle": "eye-level",
            "character_positions": [],
            "emotion": "neutral",
            "duration_hint": 3.0,
            "character_refs": [],
            "scene_ref": "",
            "reference_image_ids": [],
            "notes": "Placeholder board because no storyboard data was found.",
        }

    def _shots_by_segment(self, director_contract: dict[str, Any]) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        for shot in director_contract.get("shots", []) or []:
            try:
                segment_id = int(shot.get("segment_id"))
            except (TypeError, ValueError):
                continue
            result[segment_id] = shot
        return result

    def _shots_by_frame_id(self, director_contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for shot in director_contract.get("shots", []) or []:
            binding = shot.get("storyboard_binding", {}) if isinstance(shot, dict) else {}
            for frame_id in binding.get("storyboard_frame_ids", []) or []:
                result[str(frame_id)] = shot
        return result

    def _plates_by_segment(self, reference_plates: dict[str, Any]) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        for plate in reference_plates.get("plates", []) or []:
            try:
                segment_id = int(plate.get("segment_id"))
            except (TypeError, ValueError):
                continue
            result[segment_id] = plate
        return result

    def _image_map_by_segment(self, image_map: dict[str, Any]) -> dict[int, list[str]]:
        result: dict[int, list[str]] = {}
        for item in image_map.get("segments", []) or []:
            try:
                segment_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            result[segment_id] = [str(image) for image in item.get("images", []) or [] if image]
        return result

    def _as_int(self, value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _as_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item]
        if isinstance(value, tuple):
            return [str(item) for item in value if item]
        if isinstance(value, str):
            return [value] if value else []
        return [str(value)]

    def _dedupe_text(self, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            text = str(value).strip()
            if text and text not in result:
                result.append(text)
        return result
