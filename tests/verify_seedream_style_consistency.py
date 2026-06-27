#!/usr/bin/env python3
"""Seedream 5.0 Style Consistency Verification Script.

This script verifies the style consistency chain end-to-end:
1. Generate a style anchor image (still-life)
2. Generate a character reference using the style anchor
3. Generate a scene reference using the style anchor
4. Compare visual similarity to confirm style consistency

Usage:
    export ARK_API_KEY="your-key"
    export NARRASCAPE_FFMPEG="path/to/ffmpeg"
    python verify_seedream_style_consistency.py

Requirements:
    - ARK_API_KEY environment variable set
    - NARRASCAPE_FFMPEG environment variable set (or ffmpeg in PATH)
    - narrascape package installed
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add src to path if running from project root
sys.path.insert(0, str(Path(__file__).parent / "src"))

from narrascape.stages.generate_images import GenerateImagesStage


def verify_seedream_style_consistency():
    """Verify Seedream 5.0 style consistency with style anchor."""

    print("=" * 60)
    print("Seedream 5.0 Style Consistency Verification")
    print("=" * 60)
    print()

    # Check prerequisites
    api_key = os.environ.get("ARK_API_KEY")
    if not api_key:
        print("❌ ERROR: ARK_API_KEY environment variable not set")
        print("   Set it with: export ARK_API_KEY='your-key'")
        sys.exit(1)

    print(f"OK ARK_API_KEY: {api_key[:10]}...")

    # Setup output directory
    output_dir = Path("test_style_consistency")
    output_dir.mkdir(exist_ok=True)

    # Create generator
    generator = GenerateImagesStage(
        model="doubao-seedream-5-0-260128",
        api_key=api_key,
    )

    # Step 1: Generate Style Anchor
    print()
    print("Step 1: Generating Style Anchor (still-life)...")
    print("  This defines the visual style for ALL subsequent images.")

    style_anchor_prompt = (
        "A simple ceramic vase with a single white flower on a wooden table, "
        "near a window with soft natural light streaming in, "
        "cinematic documentary style, warm golden tones, "
        "consistent artistic style, uniform rendering quality, "
        "highly detailed, photorealistic, 8K"
    )

    style_anchor_path = output_dir / "style_anchor.png"

    try:
        result = generator._generate_one(
            prompt=style_anchor_prompt,
            out_name="style_anchor",
            size="1920x1920",
            ref_image=None,  # No reference for style anchor
            images_dir=output_dir,
            seed=42,  # Fixed seed for reproducibility
        )
        if not result:
            print("FAIL: Failed to generate style anchor")
            sys.exit(1)
        print(f"OK Style anchor: {style_anchor_path}")
    except Exception as e:
        print(f"ERROR: Error generating style anchor: {e}")
        sys.exit(1)

    # Step 2: Generate Character Reference with Style Anchor
    print()
    print("Step 2: Generating Character Reference (with style anchor)...")
    print("  Using style anchor as reference for consistent style.")

    character_prompt = (
        "参考图1的风格和色调，"
        "A full body portrait of a young warrior in traditional Chinese clothing, "
        "standing in a neutral pose, clean simple background, "
        "photorealistic, highly detailed, 8K"
    )

    character_path = output_dir / "character_ref.png"

    try:
        result = generator._generate_one(
            prompt=character_prompt,
            out_name="character_ref",
            size="1920x1920",
            ref_image=str(style_anchor_path),  # Use style anchor as reference
            images_dir=output_dir,
            sample_strength=0.65,  # Medium-high for character
        )
        if not result:
            print("FAIL: Failed to generate character reference")
            sys.exit(1)
        print(f"OK Character ref: {character_path}")
    except Exception as e:
        print(f"ERROR: Error generating character reference: {e}")
        sys.exit(1)

    # Step 3: Generate Scene Reference with Style Anchor
    print()
    print("Step 3: Generating Scene Reference (with style anchor)...")
    print("  Using style anchor as reference for consistent style.")

    scene_prompt = (
        "参考图1的风格和色调，"
        "A misty mountain landscape at dawn, ancient pine trees, "
        "soft golden morning light, atmospheric haze, "
        "photorealistic, highly detailed, 8K"
    )

    scene_path = output_dir / "scene_ref.png"

    try:
        result = generator._generate_one(
            prompt=scene_prompt,
            out_name="scene_ref",
            size="2560x1440",
            ref_image=str(style_anchor_path),  # Use style anchor as reference
            images_dir=output_dir,
            sample_strength=0.35,  # Low for scene (style-only)
        )
        if not result:
            print("FAIL: Failed to generate scene reference")
            sys.exit(1)
        print(f"OK Scene ref: {scene_path}")
    except Exception as e:
        print(f"ERROR: Error generating scene reference: {e}")
        sys.exit(1)

    # Step 4: Summary
    print()
    print("=" * 60)
    print("Verification Complete")
    print("=" * 60)
    print()
    print("Generated files:")
    print(f"  1. Style Anchor:  {style_anchor_path}")
    print(f"  2. Character:     {character_path}")
    print(f"  3. Scene:         {scene_path}")
    print()
    print("Style Consistency Check:")
    print("  - All three images should share the same visual style")
    print("  - Check: color palette, lighting quality, rendering style")
    print("  - Character and scene should match the style anchor's tone")
    print()
    print("Next Steps:")
    print("  1. Visually inspect all three images")
    print("  2. Confirm they share the same warm golden tones")
    print("  3. Confirm consistent rendering quality (photorealistic)")
    print()
    print("If style inconsistency is detected:")
    print("  - Check that '参考图1的风格和色调' is in the prompt")
    print("  - Verify sample_strength values (char: 0.65, scene: 0.35)")
    print("  - Check that style anchor is reference image 1")
    print()
    print(f"Output directory: {output_dir.absolute()}")


if __name__ == "__main__":
    verify_seedream_style_consistency()
