"""AI Director models — design report data structures."""

from __future__ import annotations

from pydantic import BaseModel, Field

from narrascape.config import MovementType, ShotType


class SegmentAnalysis(BaseModel):
    """Per-segment emotional and semantic analysis."""

    segment_id: int
    emotion: str = Field(
        ..., description="Dominant emotion: calm, tense, sad, hopeful, dramatic, nostalgic, awe"
    )
    intensity: float = Field(0.5, ge=0.0, le=1.0, description="Emotional intensity 0.0-1.0")
    scene_type: str = Field(
        ..., description="Scene setting: indoor, outdoor, abstract, portrait, landscape, urban"
    )
    key_entities: list[str] = Field(
        default_factory=list, description="Key visual subjects mentioned in text"
    )
    visual_keywords: list[str] = Field(
        default_factory=list, description="Atmosphere, lighting, weather descriptors"
    )
    pacing: str = Field("normal", description="Recommended pacing: slow, normal, fast")


class ReferenceImageChain(BaseModel):
    """Reference image chain for Seedream/Seedance multi-reference workflow.

    火山引擎即梦平台原生工作流：Seedream 图 → Seedance 视频 零损耗
    Seedream 4.0+ 支持多参考图、系列组图生成
    Seedance 2.0 支持图像/视频/音频/文本四种模态参考，最多12个文件混合参考
    """

    chain_id: str = Field(..., description="Unique chain identifier")
    chain_type: str = Field("character", description="Type: character, style, scene, or mixed")
    reference_urls: list[str] = Field(
        default_factory=list, description="Reference image URLs for this chain"
    )
    reference_local_paths: list[str] = Field(
        default_factory=list, description="Local file paths for reference images"
    )
    target_model: str = Field(
        "", description="Target model: seedream_4.6, seedream_4.0, seedance_2.0, etc."
    )
    usage_mode: str = Field(
        "reference",
        description="How to use: reference (参考图), first_frame (首帧), last_frame (尾帧), style (风格参考)",
    )
    sample_strength: float = Field(
        0.5,
        ge=0.0,
        le=1.0,
        description="Reference influence strength for Seedream. 0.0=weak, 1.0=strong. Default 0.5",
    )
    consistency_target: str = Field(
        "face", description="What to keep consistent: face, body, outfit, style, or all"
    )
    description: str = Field("", description="Human-readable description of this reference chain")
    generated_images: list[str] = Field(
        default_factory=list,
        description="URLs of generated images in this chain (for video first/last frame)",
    )


class ShotDesign(BaseModel):
    """A single shot design recommendation with three-layer model."""

    segment_id: int
    shot_type: ShotType
    movement: MovementType | None = Field(None, description="Recommended Ken Burns movement")
    size: str | None = Field(None, description="Override image dimensions if needed")
    director_vision: str = Field(
        "",
        description="Layer 1: Creative brief describing the visual world without technical terms. The director's vision in painter's language.",
    )
    cinematic_format: str = Field(
        "",
        description="Layer 3: Standardized cinematic language re-presentation of director_vision + technical parameters. Industrial shot-list format with precise terms: EXT./INT., SHOT SIZE, LENS, ANGLE, MOVEMENT, LIGHTING, COMPOSITION, COLOR, DEPTH, ATMOSPHERE, MOOD, DURATION. This determines final output quality.",
    )
    image_prompt: str = Field(
        "",
        description="Layer 2: Distilled AI image generation prompt derived from cinematic_format with character and scene consistency injected",
    )
    reasoning: str = Field("", description="Why this shot type and movement was chosen")
    style_prefix: str = Field("", description="Style prefix applied to the prompt")
    emotion: str = Field("", description="Dominant emotion for this shot")
    intensity: float = Field(0.5, ge=0.0, le=1.0, description="Emotional intensity 0.0-1.0")
    metadata: dict = Field(
        default_factory=dict,
        description="Extended fields: negative_prompt, focal_length, aperture, camera_angle, lighting_scheme, light_sources, composition, color_palette, atmosphere, depth_of_field, consistency_notes, video_readiness, key_entities, director_vision_backup, seedream_model, seedream_sample_strength, seedance_resolution",
    )
    character_refs: list[str] = Field(
        default_factory=list,
        description="Character IDs referenced in this shot. Used for consistency anchoring.",
    )
    style_ref: str = Field(
        "", description="Scene style ID referenced by this shot. Used for visual world consistency."
    )
    reference_chain_ids: list[str] = Field(
        default_factory=list,
        description="ReferenceImageChain IDs used by this shot. Enables multi-reference generation.",
    )
    seedream_model: str = Field(
        "",
        description="Recommended Seedream model: jimeng-5.0 (default), jimeng-4.6 (better face consistency), jimeng-4.0 (multi-reference)",
    )
    seedance_model: str = Field(
        "",
        description="Recommended Seedance model: jimeng-video-seedance-2.0 (full features), jimeng-video-seedance-2.0-fast (cost-effective)",
    )
    seedance_resolution: str = Field("720p", description="Video resolution: 720p or 1080p")


class CharacterProfile(BaseModel):
    """Character identity anchor for consistency across shots.

    The character profile is a "fixed identity block" that NEVER changes
    across shots. Only the scene (pose, lighting, action) changes.
    """

    char_id: str = Field(
        ..., description="Unique character identifier (e.g., 'char_001', 'protagonist')"
    )
    name: str = Field("", description="Character name if known")
    identity_block: str = Field(
        ...,
        description="FIXED identity description. Concrete physical traits that NEVER change across shots. This is the 'DNA' of the character.",
    )
    face_description: str = Field(
        "",
        description="Specific facial features: face shape, skin tone, eye shape/color, nose type, jawline, cheekbones, age cues",
    )
    hair_description: str = Field(
        "",
        description="Specific hair traits: color, length, texture, style, parting, any distinctive features",
    )
    body_description: str = Field(
        "", description="Body type, height, build, proportions, posture language"
    )
    default_outfit: str = Field(
        "",
        description="Default clothing and accessories. Can be overridden per scene via outfit_override",
    )
    signature_accessories: list[str] = Field(
        default_factory=list,
        description="Signature items that always appear (e.g., 'gold ring on left hand', 'scar on right cheek')",
    )
    outfit_override: str = Field(
        "", description="Per-scene outfit change. If empty, uses default_outfit."
    )
    expression_range: list[str] = Field(
        default_factory=list,
        description="Allowed expressions: [neutral, smiling, frowning, determined, etc.]",
    )
    # Seedream-specific optimization
    seedream_model: str = Field(
        "",
        description="Recommended Seedream model for this character: jimeng-4.6 (face consistency priority), jimeng-4.0 (multi-reference support), jimeng-5.0 (default)",
    )
    seedream_sample_strength: float = Field(
        0.5,
        ge=0.0,
        le=1.0,
        description="Reference influence strength for this character. Higher = stronger identity preservation. Default 0.5, recommend 0.6-0.8 for critical characters",
    )
    consistency_score: float = Field(
        0.0, description="Historical consistency score based on feedback (0.0-1.0)"
    )
    # Reference image for pre-production workflow
    reference_image_url: str = Field(
        "",
        description="URL or path to the character's reference anchor image. Filled by PreProductionStage.",
    )
    negative_anchors: list[str] = Field(
        default_factory=list,
        description="Anti-identity: what this character is NOT. Prevents AI from adding wrong traits.",
    )


class SceneStyle(BaseModel):
    """Visual world style guide for maintaining scene consistency.

    Defines the 'visual rules' of the film world that all shots must follow.
    """

    style_id: str = Field(
        ..., description="Unique style identifier (e.g., 'main_style', 'flashback_style')"
    )
    style_name: str = Field("", description="Human-readable name")
    base_color_temperature: str = Field(
        "",
        description="Base color temperature: warm tungsten (~3200K), daylight (~5600K), cool (~7000K), or specific Kelvin value",
    )
    color_palette: str = Field(
        "",
        description="Locked color palette for the film world. E.g., 'warm amber + deep teal + muted earth tones'",
    )
    lighting_signature: str = Field(
        "",
        description="Consistent lighting approach: e.g., 'natural light from screen left, soft diffused window light, Rembrandt lighting'",
    )
    texture_palette: str = Field(
        "",
        description="Material texture tendency: e.g., 'rough weathered wood, cracked leather, oxidized metal'",
    )
    atmosphere_signature: str = Field(
        "",
        description="Atmospheric baseline: e.g., 'pervasive dust motes in light beams, hazy distance, golden hour glow'",
    )
    depth_signature: str = Field(
        "",
        description="Depth of field tendency: e.g., 'shallow DOF for intimacy, deep for landscapes'",
    )
    lens_signature: str = Field(
        "",
        description="Preferred lens characteristics: e.g., '24mm for wide establishing, 85mm for portraits'",
    )
    style_references: list[str] = Field(
        default_factory=list,
        description="Film style references: e.g., 'Roger Deakins', 'Dune (2021)', 'Barry Jenkins'",
    )
    world_rules: list[str] = Field(
        default_factory=list,
        description="Narrative world rules: e.g., 'No modern technology', 'Always overcast', 'Warm interior vs cool exterior'",
    )
    consistency_notes: str = Field(
        "", description="Director notes on maintaining visual coherence across the sequence"
    )
    # Seedance-specific optimization
    seedance_model: str = Field(
        "",
        description="Recommended Seedance model for this style: jimeng-video-seedance-2.0 (full features), jimeng-video-seedance-2.0-fast (cost-effective)",
    )
    seedance_resolution: str = Field(
        "720p", description="Default video resolution for this style: 720p or 1080p"
    )


class ConsistencyAnchor(BaseModel):
    """Cross-shot consistency anchor that binds characters and style to each shot.

    This is the 'production binder' that ensures every shot in the sequence
    references the same visual world and character identities.
    """

    characters: list[CharacterProfile] = Field(
        default_factory=list, description="All characters in the sequence"
    )
    scene_style: SceneStyle = Field(
        default_factory=lambda: SceneStyle(style_id="default"), description="The visual world style"
    )
    consistency_rules: list[str] = Field(
        default_factory=list, description="Rules extracted from sequence analysis"
    )
    drift_warnings: list[str] = Field(
        default_factory=list, description="Warnings from consistency checks"
    )
    character_id_map: dict[str, str] = Field(
        default_factory=dict, description="Maps entity names to char_ids"
    )


class BGMZoneSuggestion(BaseModel):
    """Suggested background music zone."""

    covers: list[int] = Field(..., description="Segment IDs this zone covers")
    label: str
    prompt: str
    emotion: str


class DesignReport(BaseModel):
    """Complete design report output by AgentDirector."""

    project_title: str = ""
    style_template: str = ""
    segments: list[ShotDesign] = Field(default_factory=list)
    analysis: list[SegmentAnalysis] = Field(default_factory=list)
    bgm_zones: list[BGMZoneSuggestion] = Field(default_factory=list)
    characters: list[CharacterProfile] = Field(
        default_factory=list, description="Character profiles for consistency across shots"
    )
    scene_style: SceneStyle | None = Field(
        None, description="Visual world style guide for the sequence"
    )
    consistency_anchor: ConsistencyAnchor | None = Field(
        None, description="Cross-shot consistency anchor"
    )
    reference_image_chains: list[ReferenceImageChain] = Field(
        default_factory=list,
        description="Reference image chains for Seedream/Seedance multi-reference workflow",
    )
    style_anchor_path: str = Field(
        "",
        description="Path to the unified style anchor image for style consistency across all shots",
    )

    def to_image_prompts(self) -> dict:
        """Export as image_prompts.yaml dict with full director metadata."""
        prompts = []
        for seg in self.segments:
            entry = {
                "id": f"img_{seg.segment_id:02d}",
                "shot_type": seg.shot_type.value,
                "movement": seg.movement.value if seg.movement else None,
                "size": seg.size,
                "description": seg.image_prompt,
                "character_refs": seg.character_refs,
                "style_ref": seg.style_ref,
                "reference_chain_ids": seg.reference_chain_ids,
                "seedream_model": seg.seedream_model,
                "seedance_model": seg.seedance_model,
                "seedance_resolution": seg.seedance_resolution,
                "style_anchor_path": self.style_anchor_path,  # CRITICAL: pass style anchor for consistency
            }
            # Include extended metadata if present
            if seg.metadata:
                entry["negative_prompt"] = seg.metadata.get("negative_prompt", "")
                entry["director_vision"] = seg.director_vision
                entry["focal_length"] = seg.metadata.get("focal_length", "")
                entry["aperture"] = seg.metadata.get("aperture", "")
                entry["camera_angle"] = seg.metadata.get("camera_angle", "")
                entry["lighting_scheme"] = seg.metadata.get("lighting_scheme", "")
                entry["light_sources"] = seg.metadata.get("light_sources", [])
                entry["composition"] = seg.metadata.get("composition", "")
                entry["color_palette"] = seg.metadata.get("color_palette", "")
                entry["atmosphere"] = seg.metadata.get("atmosphere", "")
                entry["depth_of_field"] = seg.metadata.get("depth_of_field", "")
                entry["style_fingerprint"] = seg.style_prefix
                entry["reasoning"] = seg.reasoning
                entry["consistency_notes"] = seg.metadata.get("consistency_notes", "")
                entry["video_readiness"] = seg.metadata.get("video_readiness", "")
                seedream_model = seg.metadata.get("seedream_model")
                if seedream_model:
                    entry["seedream_model"] = seedream_model
                seedream_sample_strength = seg.metadata.get("seedream_sample_strength")
                if seedream_sample_strength not in (None, ""):
                    entry["seedream_sample_strength"] = seedream_sample_strength
                seedance_resolution = seg.metadata.get("seedance_resolution")
                if seedance_resolution:
                    entry["seedance_resolution"] = seedance_resolution
            # Export reference images from character profiles and reference chains
            ref_images: list[str] = []

            # CRITICAL: Add style anchor first (so it's "reference image 1" in Seedream 5.0)
            if self.style_anchor_path:
                ref_images.append(self.style_anchor_path)

            # From character profiles
            if seg.character_refs and self.characters:
                for char_ref in seg.character_refs:
                    for char in self.characters:
                        if char.char_id == char_ref:
                            if (
                                char.reference_image_url
                                and char.reference_image_url not in ref_images
                            ):
                                entry["reference_image_url"] = char.reference_image_url
                                ref_images.append(char.reference_image_url)
                            break

            # From reference chains (multi-reference support)
            if seg.reference_chain_ids and self.reference_image_chains:
                for chain_id in seg.reference_chain_ids:
                    for chain in self.reference_image_chains:
                        if chain.chain_id == chain_id:
                            for url in chain.reference_urls:
                                if url and url not in ref_images:
                                    ref_images.append(url)
                            break

            if ref_images:
                if len(ref_images) == 1:
                    entry["reference_image_url"] = ref_images[0]
                else:
                    entry["reference_images"] = ref_images
                    # Only set legacy fallback if not already set by character profile
                    if "reference_image_url" not in entry:
                        entry["reference_image_url"] = ref_images[0]

            prompts.append(entry)
        return {"prompts": prompts}

    def to_image_map(self) -> dict:
        """Export as image_map.yaml dict."""
        return {
            "segments": [
                {
                    "id": seg.segment_id,
                    "images": [f"img_{seg.segment_id:02d}"],
                }
                for seg in self.segments
            ]
        }

    def to_design_report(self) -> dict:
        """Export full design report with all director metadata for human review."""
        report = {
            "project_title": self.project_title,
            "style_template": self.style_template,
            "segments": [
                {
                    "segment_id": seg.segment_id,
                    "shot_type": seg.shot_type.value,
                    "movement": seg.movement.value if seg.movement else None,
                    "size": seg.size,
                    "director_vision": seg.director_vision,
                    "cinematic_format": seg.cinematic_format,
                    "image_prompt": seg.image_prompt,
                    "negative_prompt": (
                        seg.metadata.get("negative_prompt", "") if seg.metadata else ""
                    ),
                    "reasoning": seg.reasoning,
                    "style_fingerprint": seg.style_prefix,
                    "emotion": seg.emotion,
                    "intensity": seg.intensity,
                    "focal_length": seg.metadata.get("focal_length", "") if seg.metadata else "",
                    "aperture": seg.metadata.get("aperture", "") if seg.metadata else "",
                    "camera_angle": seg.metadata.get("camera_angle", "") if seg.metadata else "",
                    "lighting_scheme": (
                        seg.metadata.get("lighting_scheme", "") if seg.metadata else ""
                    ),
                    "light_sources": seg.metadata.get("light_sources", []) if seg.metadata else [],
                    "composition": seg.metadata.get("composition", "") if seg.metadata else "",
                    "color_palette": seg.metadata.get("color_palette", "") if seg.metadata else "",
                    "atmosphere": seg.metadata.get("atmosphere", "") if seg.metadata else "",
                    "depth_of_field": (
                        seg.metadata.get("depth_of_field", "") if seg.metadata else ""
                    ),
                    "consistency_notes": (
                        seg.metadata.get("consistency_notes", "") if seg.metadata else ""
                    ),
                    "video_readiness": (
                        seg.metadata.get("video_readiness", "") if seg.metadata else ""
                    ),
                    "key_entities": seg.metadata.get("key_entities", "") if seg.metadata else "",
                    "character_refs": seg.character_refs,
                    "style_ref": seg.style_ref,
                    "reference_chain_ids": seg.reference_chain_ids,
                    "seedream_model": seg.seedream_model,
                    "seedance_model": seg.seedance_model,
                    "seedance_resolution": seg.seedance_resolution,
                }
                for seg in self.segments
            ],
            "bgm_zones": [
                {
                    "covers": z.covers,
                    "label": z.label,
                    "prompt": z.prompt,
                    "emotion": z.emotion,
                }
                for z in self.bgm_zones
            ],
            "characters": [
                {
                    "char_id": c.char_id,
                    "name": c.name,
                    "identity_block": c.identity_block,
                    "face_description": c.face_description,
                    "hair_description": c.hair_description,
                    "body_description": c.body_description,
                    "default_outfit": c.default_outfit,
                    "signature_accessories": c.signature_accessories,
                    "negative_anchors": c.negative_anchors,
                    "reference_image_url": c.reference_image_url,
                    "seedream_model": c.seedream_model,
                    "seedream_sample_strength": c.seedream_sample_strength,
                }
                for c in self.characters
            ],
            "scene_style": (
                {
                    "style_id": self.scene_style.style_id if self.scene_style else "default",
                    "style_name": self.scene_style.style_name if self.scene_style else "",
                    "base_color_temperature": (
                        self.scene_style.base_color_temperature if self.scene_style else ""
                    ),
                    "color_palette": self.scene_style.color_palette if self.scene_style else "",
                    "lighting_signature": (
                        self.scene_style.lighting_signature if self.scene_style else ""
                    ),
                    "texture_palette": self.scene_style.texture_palette if self.scene_style else "",
                    "atmosphere_signature": (
                        self.scene_style.atmosphere_signature if self.scene_style else ""
                    ),
                    "style_references": (
                        self.scene_style.style_references if self.scene_style else []
                    ),
                    "world_rules": self.scene_style.world_rules if self.scene_style else [],
                    "seedance_model": self.scene_style.seedance_model if self.scene_style else "",
                    "seedance_resolution": (
                        self.scene_style.seedance_resolution if self.scene_style else ""
                    ),
                }
                if self.scene_style
                else None
            ),
            "reference_image_chains": [
                {
                    "chain_id": r.chain_id,
                    "chain_type": r.chain_type,
                    "reference_urls": r.reference_urls,
                    "reference_local_paths": r.reference_local_paths,
                    "target_model": r.target_model,
                    "usage_mode": r.usage_mode,
                    "sample_strength": r.sample_strength,
                    "consistency_target": r.consistency_target,
                    "description": r.description,
                    "generated_images": r.generated_images,
                }
                for r in self.reference_image_chains
            ],
        }
        return report


# ═══════════════════════════════════════════════════════════════════
# Pre-Production Models — Reference Images & Storyboard
# ═══════════════════════════════════════════════════════════════════


class CharacterReferenceImage(BaseModel):
    """A single reference image for a character (anchor, turn, expression, etc.)."""

    image_id: str = Field(..., description="Unique image ID, e.g., 'char_001_anchor'")
    image_type: str = Field(
        ...,
        description="Type: anchor (全身锚点图), turn_front, turn_side, turn_back, expression_neutral, expression_happy, expression_sad, expression_angry, dynamic_pose, outfit_detail",
    )
    local_path: str = Field("", description="Local file path to the generated image")
    url: str = Field("", description="URL if uploaded to cloud")
    prompt: str = Field("", description="The prompt used to generate this image")
    model: str = Field("", description="Model used to generate this image")
    sample_strength: float = Field(0.5, ge=0.0, le=1.0, description="Reference strength used")
    description: str = Field("", description="Human-readable description of this image")


class CharacterReferenceSheet(BaseModel):
    """Complete reference sheet for a single character.

    Follows industry-standard animation character design specification:
    - anchor: 正面全身锚点图 (the most critical — all other images reference this)
    - turns: 多角度转面图 (front, side, back)
    - expressions: 常用表情图
    - dynamics: 常用动态图
    - outfit: 服装道具图
    """

    char_id: str = Field(..., description="Character ID matching CharacterProfile.char_id")
    name: str = Field("", description="Character name")
    identity_block: str = Field("", description="Identity description used for generation")
    anchor_image: CharacterReferenceImage | None = Field(
        None, description="正面全身锚点图 — the master reference"
    )
    turn_images: list[CharacterReferenceImage] = Field(
        default_factory=list, description="转面图: front, side, back"
    )
    expression_images: list[CharacterReferenceImage] = Field(
        default_factory=list, description="表情图: neutral, happy, sad, angry, etc."
    )
    dynamic_images: list[CharacterReferenceImage] = Field(
        default_factory=list, description="动态图: key poses showing character personality"
    )
    outfit_images: list[CharacterReferenceImage] = Field(
        default_factory=list, description="服装道具图"
    )
    # Convenience: primary reference for downstream use
    primary_reference_path: str = Field(
        "", description="Path to the anchor image (or first available reference)"
    )
    seedream_model: str = Field("", description="Recommended model for this character")
    seedream_sample_strength: float = Field(
        0.5, ge=0.0, le=1.0, description="Default sample strength for this character"
    )


class EnvironmentReferenceImage(BaseModel):
    """A single reference image for an environment/scene."""

    image_id: str = Field(..., description="Unique image ID, e.g., 'scene_001_mood'")
    image_type: str = Field(
        ..., description="Type: mood (氛围图), landmark (地标), interior, exterior, detail"
    )
    local_path: str = Field("", description="Local file path")
    url: str = Field("", description="URL if uploaded")
    prompt: str = Field("", description="Generation prompt")
    model: str = Field("", description="Model used")
    description: str = Field("", description="Human-readable description")


class EnvironmentReference(BaseModel):
    """Reference images for a single scene/environment."""

    scene_id: str = Field(..., description="Scene identifier, e.g., 'scene_001'")
    scene_name: str = Field("", description="Human-readable scene name")
    scene_type: str = Field("", description="indoor, outdoor, urban, natural, abstract, etc.")
    mood_images: list[EnvironmentReferenceImage] = Field(
        default_factory=list, description="氛围图: lighting, color, atmosphere"
    )
    landmark_images: list[EnvironmentReferenceImage] = Field(
        default_factory=list, description="地标图: key landmarks or set pieces"
    )
    detail_images: list[EnvironmentReferenceImage] = Field(
        default_factory=list, description="细节图: textures, props, architectural details"
    )
    primary_reference_path: str = Field("", description="Path to primary mood image")
    time_of_day: str = Field("", description="day, night, dawn, dusk, etc.")
    weather: str = Field("", description="clear, rainy, foggy, snowy, etc.")
    lighting_signature: str = Field("", description="Consistent lighting description")
    color_palette: str = Field("", description="Locked color palette for this scene")


class StoryboardFrame(BaseModel):
    """A single frame in a storyboard."""

    frame_id: str = Field(..., description="Unique frame ID, e.g., 'sb_001_01'")
    segment_id: int = Field(..., description="Which script segment this frame belongs to")
    frame_index: int = Field(0, description="Frame index within the segment (0, 1, 2...)")
    description: str = Field(
        "", description="Visual description: composition, character positions, action"
    )
    shot_type: str = Field("", description="Recommended shot type: wide, medium, close-up, etc.")
    camera_movement: str = Field(
        "", description="Camera movement: static, pan, tilt, dolly, zoom, etc."
    )
    camera_angle: str = Field(
        "", description="Camera angle: eye-level, low-angle, high-angle, overhead, etc."
    )
    character_positions: list[str] = Field(
        default_factory=list, description="Where each character is positioned in frame"
    )
    emotion: str = Field("", description="Frame emotion")
    duration_hint: float = Field(3.0, description="Suggested duration in seconds")
    character_refs: list[str] = Field(
        default_factory=list, description="Character IDs present in this frame"
    )
    scene_ref: str = Field("", description="Scene ID referenced")
    reference_image_ids: list[str] = Field(
        default_factory=list, description="IDs of reference images to use for this frame"
    )
    notes: str = Field("", description="Director notes for this frame")


class Storyboard(BaseModel):
    """Complete storyboard for the entire project."""

    project_title: str = ""
    frames: list[StoryboardFrame] = Field(
        default_factory=list, description="All storyboard frames in sequence"
    )
    total_frames: int = Field(0, description="Total number of frames")
    total_segments: int = Field(0, description="Number of segments covered")

    def frames_for_segment(self, segment_id: int) -> list[StoryboardFrame]:
        """Get all frames belonging to a specific segment."""
        return [f for f in self.frames if f.segment_id == segment_id]


class PreProductionReport(BaseModel):
    """Complete pre-production report output by PreProductionStage.

    Contains all reference images and storyboard generated before DesignStage.
    """

    project_title: str = ""
    style_template: str = ""
    characters: list[CharacterReferenceSheet] = Field(
        default_factory=list, description="Character reference sheets"
    )
    environments: list[EnvironmentReference] = Field(
        default_factory=list, description="Scene environment references"
    )
    storyboard: Storyboard = Field(
        default_factory=lambda: Storyboard(), description="Complete storyboard"
    )

    # Convenience exports
    def to_character_refs_dict(self) -> dict:
        """Export character reference paths for DesignStage consumption."""
        return {
            c.char_id: c.primary_reference_path for c in self.characters if c.primary_reference_path
        }

    def to_scene_refs_dict(self) -> dict:
        """Export scene reference paths for DesignStage consumption."""
        return {
            e.scene_id: e.primary_reference_path
            for e in self.environments
            if e.primary_reference_path
        }

    def to_storyboard_frames(self) -> list[dict]:
        """Export storyboard frames as plain dicts."""
        return [f.model_dump() for f in self.storyboard.frames]

    def to_pre_production_report(self) -> dict:
        """Export full report for human review."""
        return {
            "project_title": self.project_title,
            "style_template": self.style_template,
            "characters": [
                {
                    "char_id": c.char_id,
                    "name": c.name,
                    "identity_block": c.identity_block,
                    "primary_reference_path": c.primary_reference_path,
                    "seedream_model": c.seedream_model,
                    "seedream_sample_strength": c.seedream_sample_strength,
                    "anchor_image": c.anchor_image.model_dump() if c.anchor_image else None,
                    "turn_images": [i.model_dump() for i in c.turn_images],
                    "expression_images": [i.model_dump() for i in c.expression_images],
                    "dynamic_images": [i.model_dump() for i in c.dynamic_images],
                    "outfit_images": [i.model_dump() for i in c.outfit_images],
                }
                for c in self.characters
            ],
            "environments": [
                {
                    "scene_id": e.scene_id,
                    "scene_name": e.scene_name,
                    "scene_type": e.scene_type,
                    "primary_reference_path": e.primary_reference_path,
                    "time_of_day": e.time_of_day,
                    "weather": e.weather,
                    "lighting_signature": e.lighting_signature,
                    "color_palette": e.color_palette,
                    "mood_images": [i.model_dump() for i in e.mood_images],
                    "landmark_images": [i.model_dump() for i in e.landmark_images],
                    "detail_images": [i.model_dump() for i in e.detail_images],
                }
                for e in self.environments
            ],
            "storyboard": {
                "total_frames": self.storyboard.total_frames,
                "total_segments": self.storyboard.total_segments,
                "frames": [f.model_dump() for f in self.storyboard.frames],
            },
        }
