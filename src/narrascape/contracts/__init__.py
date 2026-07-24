"""Typed pydantic models for the core stage-to-stage contracts.

These models complement (not replace) the lightweight top-level checks in
`narrascape.artifacts`: writers validate the full payload through the model
before the artifact gate and the YAML write, so schema drift fails at the
write point. Readers may use the models for typed access, with a documented
fallback to raw dict access for artifacts that predate the models.
"""

from narrascape.contracts.common import ContractModel, ProjectRef
from narrascape.contracts.director_contract import (
    CompileProcess,
    ContinuityConstraints,
    DirectorContract,
    DirectorShot,
    FilmLanguage,
    GenerationContract,
    StoryboardBinding,
)
from narrascape.contracts.film_supervisor import (
    FilmSupervisorReport,
    SupervisorDecision,
)
from narrascape.contracts.film_timeline import (
    FilmTimeline,
    TimelineCoverage,
    TimelineTracks,
    VisualClip,
)

__all__ = [
    "CompileProcess",
    "ContinuityConstraints",
    "ContractModel",
    "DirectorContract",
    "DirectorShot",
    "FilmLanguage",
    "FilmSupervisorReport",
    "FilmTimeline",
    "GenerationContract",
    "ProjectRef",
    "StoryboardBinding",
    "SupervisorDecision",
    "TimelineCoverage",
    "TimelineTracks",
    "VisualClip",
]
