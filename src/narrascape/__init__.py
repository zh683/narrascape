"""
narrascape — Production-grade video pipeline for book explainer and documentary content.

Key features:
- Ken Burns motion with three-tier rendering (zoompan / crop / PIL sub-pixel)
- Parallel segment rendering with progress tracking
- Content-hash driven incremental builds
- Provider plugin system for TTS, Image, and Music generation
- Pydantic-validated configuration with auto-completion
"""

__version__ = "0.1.0"

from narrascape.config import NarrascapeConfig, load_config
from narrascape.pipeline import Pipeline

__all__ = ["__version__", "Pipeline", "NarrascapeConfig", "load_config"]
