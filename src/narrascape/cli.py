#!/usr/bin/env python3
"""
Narrascape Pipeline CLI — typer-based command-line interface.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, Literal, TextIO, cast

import typer
from rich.console import Console
from rich.table import Table

from narrascape import __version__
from narrascape.api_keys import APIKeys
from narrascape.application import ApprovalService, PipelineRunService, validate_stage_name
from narrascape.config import (
    DEFAULT_VISUAL_STYLE,
    ImageProvider,
    NarrascapeConfig,
    Script,
    ScriptSegment,
    VideoProvider,
    load_config,
    load_script,
)
from narrascape.log_setup import setup_logging
from narrascape.utils.safe_io import atomic_copy_file, atomic_write_yaml

LLMProviderName = Literal[
    "openai", "anthropic", "deepseek", "volcengine", "local", "bridge", "ai_assistant"
]

app = typer.Typer(
    name="narrascape",
    help="Production-grade video pipeline for book explainer and documentary content.",
    rich_markup_mode="rich",
)
benchmark_app = typer.Typer(help="Record and report fixed production benchmarks.")
app.add_typer(benchmark_app, name="benchmark")


def _reconfigure_text_stream(stream: TextIO | Any) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")


# Handle Windows encoding for emoji output
if sys.platform == "win32":
    try:
        _reconfigure_text_stream(sys.stdout)
        _reconfigure_text_stream(sys.stderr)
    except (AttributeError, ValueError):
        pass

console = Console(force_terminal=True, emoji=False if sys.platform == "win32" else True)

PRODUCTION_PROFILE_NAME = "seedream-seedance-oil-painting"
PRODUCTION_OIL_PAINTING_STYLE = (
    "Oil painting style, painterly cinematic AI-film frames, visible brush texture, "
    "layered pigments, canvas grain, rich chiaroscuro lighting, cohesive period-drama "
    "color palette, character-led composition, restrained cinematic motion; "
    "not photorealistic photography, not anime, not cartoon, no readable text, "
    "no watermark, no platform label."
)


def _benchmark_repository(catalog_path: Path, database_path: Path) -> Any:
    from narrascape.benchmarks import BenchmarkCatalog, BenchmarkRunRepository

    return BenchmarkRunRepository(database_path, BenchmarkCatalog.load(catalog_path))


@benchmark_app.command("list")
def benchmark_list_cmd(
    catalog_path: Annotated[Path, typer.Option("--catalog", help="Benchmark catalog YAML")] = Path(
        "benchmarks/catalog.yaml"
    ),
) -> None:
    """List the fixed production benchmarks."""
    from narrascape.benchmarks import BenchmarkCatalog

    catalog = BenchmarkCatalog.load(catalog_path)
    table = Table("Benchmark", "Type", "Project")
    for item in catalog.benchmarks:
        table.add_row(item.id, item.production_type, item.project_path)
    console.print(table)


@benchmark_app.command("record")
def benchmark_record_cmd(
    benchmark_id: Annotated[str, typer.Option("--benchmark")],
    project_id: Annotated[str, typer.Option("--project-id")],
    operator_id: Annotated[str, typer.Option("--operator-id")],
    cost_usd: Annotated[float, typer.Option("--cost-usd", min=0.0)],
    elapsed_seconds: Annotated[float, typer.Option("--elapsed-seconds", min=0.0)],
    manual_reworks: Annotated[int, typer.Option("--manual-reworks", min=0)],
    quality_score: Annotated[float, typer.Option("--quality-score", min=0.0, max=100.0)],
    run_mode: Annotated[
        Literal["production", "offline", "synthetic"], typer.Option("--run-mode")
    ] = "synthetic",
    real_user: Annotated[bool, typer.Option("--real-user/--synthetic")] = False,
    success: Annotated[bool, typer.Option("--success/--failed")] = False,
    notes: Annotated[str, typer.Option("--notes")] = "",
    catalog_path: Annotated[Path, typer.Option("--catalog", help="Benchmark catalog YAML")] = Path(
        "benchmarks/catalog.yaml"
    ),
    database_path: Annotated[
        Path, typer.Option("--database", help="Benchmark SQLite database")
    ] = Path(".narrascape/benchmarks.sqlite3"),
) -> None:
    """Record one completed benchmark production and its human quality score."""
    from narrascape.benchmarks import BenchmarkRunInput

    repository = _benchmark_repository(catalog_path, database_path)
    record = repository.record(
        BenchmarkRunInput(
            benchmark_id=benchmark_id,
            project_id=project_id,
            operator_id=operator_id,
            real_user=real_user,
            success=success,
            cost_usd=cost_usd,
            elapsed_seconds=elapsed_seconds,
            manual_reworks=manual_reworks,
            quality_score=quality_score,
            run_mode=run_mode,
            notes=notes,
        )
    )
    console.print(
        f"[green]Recorded[/] {record.benchmark_id} project={record.project_id} id={record.id}"
    )


@benchmark_app.command("report")
def benchmark_report_cmd(
    catalog_path: Annotated[Path, typer.Option("--catalog", help="Benchmark catalog YAML")] = Path(
        "benchmarks/catalog.yaml"
    ),
    database_path: Annotated[
        Path, typer.Option("--database", help="Benchmark SQLite database")
    ] = Path(".narrascape/benchmarks.sqlite3"),
) -> None:
    """Show aggregate production metrics and the beta release gate."""
    report = _benchmark_repository(catalog_path, database_path).report()
    table = Table("Benchmark", "Runs", "Success", "Cost USD", "Time s", "Reworks", "Quality")
    for benchmark_id, metrics in report["by_benchmark"].items():
        table.add_row(
            benchmark_id,
            str(metrics["run_count"]),
            f"{metrics['success_rate']:.0%}",
            f"{metrics['total_cost_usd']:.2f}",
            f"{metrics['total_elapsed_seconds']:.1f}",
            str(metrics["total_manual_reworks"]),
            f"{metrics['average_quality_score']:.1f}",
        )
    console.print(table)
    gate = report["release_gate"]
    status = "READY" if gate["ready"] else "NOT READY"
    console.print(
        f"Release gate: [bold]{status}[/] | real projects "
        f"{gate['real_project_count']}/{gate['required_real_projects']} | "
        f"success {gate['success_rate']:.0%} | quality {gate['average_quality_score']:.1f}"
    )


@contextmanager
def _temporary_env(name: str, value: str) -> Iterator[None]:
    previous = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def _empty_script() -> Script:
    return Script(segments=[ScriptSegment(id=1, text="")])


def _load_script_or_empty(config: NarrascapeConfig) -> Script:
    return load_script(config.script_path) if config.script_path.exists() else _empty_script()


def _pre_production_report_output(outputs: Any) -> str:
    if isinstance(outputs, dict):
        return str(outputs.get("pre_production_report", ""))
    return ""


def _apply_build_profile(
    config: NarrascapeConfig,
    *,
    profile: str = "",
    production: bool = False,
) -> NarrascapeConfig:
    """Apply runtime build profile defaults without mutating config.yaml."""
    requested_profile = profile.strip().lower()
    if production and not requested_profile:
        requested_profile = PRODUCTION_PROFILE_NAME
    if not requested_profile:
        return config
    if requested_profile != PRODUCTION_PROFILE_NAME:
        raise ValueError(
            f"Unknown build profile {profile!r}. Supported profile: {PRODUCTION_PROFILE_NAME}"
        )

    updated = config.model_copy(deep=True)
    updated.images.provider = ImageProvider.SEEDREAM
    updated.images.style = PRODUCTION_OIL_PAINTING_STYLE
    updated.video.provider = VideoProvider.SEEDANCE
    updated.video.takes = max(updated.video.takes, 3)
    updated.pipeline.video_generation = "required"
    updated.pipeline.strict_director = True
    updated.pipeline.production_quality_gates = True
    updated.pipeline.auto_rework = True
    updated.pipeline.max_rework_cycles = max(updated.pipeline.max_rework_cycles, 2)
    if updated.llm.mode == "none":
        updated.llm.mode = "ai_assistant"
    return updated


def _status_stage_names() -> list[str]:
    from narrascape.pipeline import ALL_STAGES

    return [stage_cls().name for stage_cls in ALL_STAGES]


def _validated_stage_name(stage_name: str) -> str:
    try:
        return validate_stage_name(stage_name)
    except ValueError as exc:
        raise typer.BadParameter(f"Unknown stage: {stage_name}", param_hint="--stage") from exc


# ═══════════════════════════════════════════
# LLM Client Factory
# ═══════════════════════════════════════════

from narrascape.llm import LLMClient
from narrascape.llm import LLMConfig as LLMClientConfig


def _llm_client_config(
    project_config: NarrascapeConfig | None,
    **runtime_options: Any,
) -> LLMClientConfig:
    """Map project log-governance settings into the runtime LLM config."""

    if project_config is not None:
        logging_config = project_config.llm
        runtime_options.update(
            log_enabled=logging_config.log_enabled,
            log_max_entries=logging_config.log_max_entries,
            log_max_text_chars=logging_config.log_max_text_chars,
            log_include_parsed_output=logging_config.log_include_parsed_output,
            log_persist_path=(
                project_config.project_dir / ".narrascape" / "llm-calls.json"
                if logging_config.log_persist
                else None
            ),
        )
    return LLMClientConfig(**runtime_options)


def _get_llm_client(
    api_key: str | NarrascapeConfig | None = None, config: NarrascapeConfig | None = None
) -> LLMClient | None:
    """Create a production-grade LLM client with multi-provider support.

    Priority: config.llm.mode > env NARRASCAPE_LLM_MODE > explicit key > env vars > auto-detection
    Supports: AI Assistant/Bridge (project-local file tasks), OpenAI, Anthropic, DeepSeek, Volcengine/Ark, local

    AI Assistant mode is the default when no external API keys are configured.
    The AI assistant (e.g., Kimi, Codex) processes project-local bridge tasks without needing external API keys.
    """
    if isinstance(api_key, NarrascapeConfig) and config is None:
        config = api_key
        api_key = None
    explicit_api_key = api_key if isinstance(api_key, str) else None

    if config:
        os.environ.setdefault(
            "NARRASCAPE_BRIDGE_DIR",
            str(config.project_dir / ".narrascape" / "bridge"),
        )

    # Check config.yaml first
    if config and config.llm.mode in ("ai_assistant", "bridge", "api", "none"):
        if config.llm.mode == "ai_assistant":
            console.print("[bold green]AI Assistant Mode[/] - using project-local assistant bridge")
            os.environ["NARRASCAPE_LLM_MODE"] = "ai_assistant"
            return LLMClient(
                _llm_client_config(
                    config,
                    provider="ai_assistant",
                    temperature=config.llm.temperature,
                    max_tokens=config.llm.max_tokens,
                    max_retries=3,
                    retry_delay=2.0,
                    json_mode=True,
                )
            )
        elif config.llm.mode == "bridge":
            console.print("[bold cyan]Bridge Mode[/] — delegating to AI assistant via file tasks")
            os.environ["NARRASCAPE_LLM_MODE"] = "bridge"
            if config.llm.timeout:
                os.environ["NARRASCAPE_BRIDGE_TIMEOUT"] = str(config.llm.timeout)
            return LLMClient(
                _llm_client_config(
                    config,
                    provider="bridge",
                    temperature=config.llm.temperature,
                    max_tokens=config.llm.max_tokens,
                    max_retries=3,
                    retry_delay=2.0,
                    json_mode=True,
                )
            )
        elif config.llm.mode == "api":
            # Use config API settings
            if config.llm.api_key:
                return LLMClient(
                    _llm_client_config(
                        config,
                        provider=cast(LLMProviderName, config.llm.provider or "openai"),
                        model=config.llm.model or "gpt-4o",
                        api_key=config.llm.api_key,
                        base_url=config.llm.base_url or None,
                        temperature=config.llm.temperature,
                        max_tokens=config.llm.max_tokens,
                        max_retries=3,
                        retry_delay=2.0,
                        json_mode=True,
                    )
                )
        elif config.llm.mode == "none":
            if config.pipeline.video_generation == "required":
                console.print(
                    "[bold yellow]AI Assistant Mode[/] - video_generation=required cannot "
                    "run with llm.mode=none; using project-local assistant bridge"
                )
                os.environ["NARRASCAPE_LLM_MODE"] = "ai_assistant"
                return LLMClient(
                    _llm_client_config(
                        config,
                        provider="ai_assistant",
                        temperature=config.llm.temperature,
                        max_tokens=config.llm.max_tokens,
                        max_retries=3,
                        retry_delay=2.0,
                        json_mode=True,
                    )
                )
            console.print("[bold yellow]Offline LLM Mode[/] - using deterministic/template stages")
            return None

    # Try env var ai_assistant mode
    if os.environ.get("NARRASCAPE_LLM_MODE", "").lower() == "ai_assistant":
        console.print("[bold green]AI Assistant Mode[/] - using project-local assistant bridge")
        return LLMClient(
            _llm_client_config(
                config,
                provider="ai_assistant",
                temperature=0.7,
                max_tokens=4000,
                max_retries=3,
                retry_delay=2.0,
                json_mode=True,
            )
        )

    # Try env var bridge mode
    if os.environ.get("NARRASCAPE_LLM_MODE", "").lower() == "bridge":
        console.print("[bold cyan]Bridge Mode[/] — delegating to AI assistant via file tasks")
        return LLMClient(
            _llm_client_config(
                config,
                provider="bridge",
                temperature=0.7,
                max_tokens=4000,
                max_retries=3,
                retry_delay=2.0,
                json_mode=True,
            )
        )

    # Try explicit API key
    key = explicit_api_key or APIKeys.openai()
    if key:
        return LLMClient(
            _llm_client_config(
                config,
                provider="openai",
                model="gpt-4o",
                api_key=key,
                temperature=0.7,
                max_tokens=2000,
                max_retries=3,
                retry_delay=2.0,
                json_mode=True,
            )
        )

    # Try Ark (Volcengine)
    key = APIKeys.ark()
    if key:
        base = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
        model = os.environ.get("ARK_MODEL_ID", "doubao-pro-32k")
        return LLMClient(
            _llm_client_config(
                config,
                provider="openai",
                model=model,
                api_key=key,
                base_url=base,
                temperature=0.7,
                max_tokens=2000,
                max_retries=3,
                retry_delay=2.0,
                json_mode=True,
            )
        )

    # Auto-detect from environment (defaults to AI Assistant mode if no API keys)
    client = LLMClient.from_env(allow_bridge=True)
    if config is not None:
        governed_config = _llm_client_config(
            config,
            provider=client.config.provider,
            model=client.config.model,
            api_key=client.config.api_key,
            base_url=client.config.base_url,
            temperature=client.config.temperature,
            max_tokens=client.config.max_tokens,
            top_p=client.config.top_p,
            timeout=client.config.timeout,
            max_retries=client.config.max_retries,
            retry_delay=client.config.retry_delay,
            system_prompt=client.config.system_prompt,
            json_mode=client.config.json_mode,
        )
        client = LLMClient(governed_config)
    if client and client.config.provider == "ai_assistant":
        console.print(
            "[bold green]AI Assistant Mode[/] - using project-local assistant bridge (no API keys needed)"
        )
    return client


# ═══════════════════════════════════════════
# Global options
# ═══════════════════════════════════════════


@app.callback()
def global_options(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress non-error output")] = False,
) -> None:
    """Global options for all commands."""
    level = "ERROR" if quiet else ("DEBUG" if verbose else "INFO")
    setup_logging(level=level)


# ═══════════════════════════════════════════
# Init command
# ═══════════════════════════════════════════


@app.command("init")
def init_cmd(
    project_name: Annotated[str, typer.Argument(help="Project directory name")],
    title: Annotated[str, typer.Option("--title", "-t", help="Video title")] = "",
    script_file: Annotated[
        str, typer.Option("--script", help="Script file path")
    ] = "scripts/script.yaml",
) -> None:
    """Initialize a new narrascape project with scaffolding."""
    project_dir = Path(project_name).resolve()
    project_slug = project_dir.name
    if project_dir.exists():
        console.print(f"[bold red]Error:[/] Directory already exists: {project_dir}")
        raise typer.Exit(1)

    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "scripts").mkdir(exist_ok=True)
    (project_dir / "assets" / "images").mkdir(parents=True, exist_ok=True)
    (project_dir / "assets" / "tts").mkdir(parents=True, exist_ok=True)
    (project_dir / "assets" / "music").mkdir(parents=True, exist_ok=True)
    (project_dir / "assets" / "videos").mkdir(parents=True, exist_ok=True)
    (project_dir / "pipeline").mkdir(exist_ok=True)
    (project_dir / "output").mkdir(exist_ok=True)

    config = {
        "project": {
            "name": project_slug,
            "title": title or project_slug.replace("-", " ").replace("_", " ").title(),
            "script_file": script_file,
        },
        "pipeline": {
            "name": "animated-explainer",
            "version": "2.0",
            "video_generation": "auto",
        },
        "images": {
            "provider": "seedream",
            "model": "doubao-seedream-5-0-260128",
            "style": DEFAULT_VISUAL_STYLE,
        },
        "video": {
            "provider": "seedance",
            "model": "jimeng-video-seedance-2.0",
            "resolution": "720p",
            "ratio": "16:9",
            "duration": 5,
            "frame_rate": 24,
            "takes": 1,
        },
    }
    atomic_write_yaml(project_dir / "config.yaml", config)

    script = {
        "title": title or project_name,
        "segments": [
            {
                "id": 1,
                "text": "Your narration text here. Replace this with your actual script content.",
                "shot_type": "medium",
            }
        ],
    }
    atomic_write_yaml(project_dir / "scripts" / "script.yaml", script)

    console.print(f"[bold green]Project initialized:[/] {project_dir}")
    console.print("  - config.yaml")
    console.print("  - scripts/script.yaml")
    console.print("  - assets/ (images, tts, music, videos)")
    console.print("  - pipeline/")
    console.print("  - output/")


# ═══════════════════════════════════════════
# Dashboard command
# ═══════════════════════════════════════════


@app.command("dashboard")
def dashboard_cmd(
    project_dir: Annotated[
        Path,
        typer.Option(
            "--project", "-p", help="Project directory", exists=True, file_okay=False, dir_okay=True
        ),
    ] = Path("."),
    port: Annotated[int, typer.Option("--port", help="Streamlit server port")] = 8501,
    host: Annotated[str, typer.Option("--host", "-h", help="Bind address")] = "127.0.0.1",
) -> None:
    """Launch the interactive web-based control panel."""
    from narrascape.cli_runtime import OptionalRuntimeError, launch_streamlit_diagnostics

    dashboard_path = Path(__file__).parent / "dashboard.py"
    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        console.print(f"[bold red]Error:[/] config.yaml not found in {project_dir}")
        raise typer.Exit(1)

    project_dir = project_dir.resolve()
    console.print(f"[bold green]Launching Narrascape Dashboard[/] at http://{host}:{port}")
    console.print(f"[dim]Project:[/] {project_dir}")
    console.print("Press [bold]Ctrl+C[/] to stop.")
    try:
        launch_streamlit_diagnostics(
            project_dir,
            dashboard_path=dashboard_path,
            host=host,
            port=port,
        )
    except KeyboardInterrupt:
        console.print("[bold yellow]Dashboard stopped.")
    except (OptionalRuntimeError, OSError, subprocess.SubprocessError) as e:
        console.print(f"[bold red]Failed to launch dashboard:[/] {e}")
        raise typer.Exit(1)


@app.command("workbench")
def workbench_cmd(
    project_dir: Annotated[
        Path,
        typer.Option(
            "--project", "-p", help="Project directory", exists=True, file_okay=False, dir_okay=True
        ),
    ] = Path("."),
    port: Annotated[int, typer.Option("--port", help="Workbench server port")] = 8765,
    host: Annotated[str, typer.Option("--host", help="Bind address")] = "127.0.0.1",
) -> None:
    """Launch the native React production workflow control plane."""
    from narrascape.cli_runtime import OptionalRuntimeError, launch_native_workbench

    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        console.print(f"[bold red]Error:[/] config.yaml not found in {project_dir}")
        raise typer.Exit(1)
    project_dir = project_dir.resolve()
    console.print(f"[bold green]Narrascape 制作工作台[/] http://{host}:{port}")
    console.print(f"[dim]项目：[/] {project_dir}")
    try:
        launch_native_workbench(project_dir, host=host, port=port)
    except KeyboardInterrupt:
        console.print("[bold yellow]制作工作台已停止。[/]")
    except OptionalRuntimeError as exc:
        console.print(f"[bold red]Error:[/] {exc}")
        raise typer.Exit(1)


# ═══════════════════════════════════════════
# Research command
# ═══════════════════════════════════════════


@app.command("research")
def research_cmd(
    topic: Annotated[
        str, typer.Argument(help="Topic to research (e.g. 'AI history', 'Ancient Rome')")
    ],
    project_dir: Annotated[
        Path,
        typer.Option(
            "--project", "-p", help="Project directory", exists=True, file_okay=False, dir_okay=True
        ),
    ] = Path("."),
    depth: Annotated[
        str, typer.Option("--depth", "-d", help="Research depth: brief, standard, deep")
    ] = "standard",
) -> None:
    """Research a topic and save findings for script writing.

    Generates research_report.md with structured findings.
    """
    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        console.print(f"[bold red]Error:[/] config.yaml not found in {project_dir}")
        raise typer.Exit(1)

    try:
        config = load_config(config_path)
    except Exception as e:
        console.print(f"[bold red]Config error:[/] {e}")
        raise typer.Exit(1)

    from narrascape.cache import BuildCache
    from narrascape.stages.base import StageContext
    from narrascape.stages.research import ResearchStage

    stage = ResearchStage(llm_client=_get_llm_client(config=config), topic=topic, depth=depth)
    context = StageContext(
        config=config,
        script=_empty_script(),
        cache=BuildCache(config.pipeline_dir / ".cache"),
        state={},
        dry_run=False,
    )

    result = stage.run(context)
    if not result.success:
        console.print(f"[bold red]Research failed:[/] {result.message}")
        raise typer.Exit(1)


# ═══════════════════════════════════════════
# Write command (AI script writer)
# ═══════════════════════════════════════════


@app.command("write")
def write_cmd(
    topic: Annotated[
        str | None,
        typer.Argument(help="Topic to write about (optional if using existing research)"),
    ] = None,
    project_dir: Annotated[
        Path,
        typer.Option(
            "--project", "-p", help="Project directory", exists=True, file_okay=False, dir_okay=True
        ),
    ] = Path("."),
    segments: Annotated[
        int, typer.Option("--segments", "-n", help="Number of segments to write")
    ] = 12,
    style: Annotated[
        str,
        typer.Option(
            "--style", "-s", help="Writing style: documentary, narrative, educational, poetic"
        ),
    ] = "documentary",
    research_report: Annotated[
        str | None, typer.Option("--research", "-r", help="Path to existing research report")
    ] = None,
    skip_humanize: Annotated[
        bool, typer.Option("--skip-humanize", help="Skip AI de-humanization pass")
    ] = False,
) -> None:
    """Write narration script from topic or research report.

    Generates:
    - scripts/script_raw.yaml (AI raw output)
    - scripts/script.yaml (humanized, EDIT THIS)
    - .approval_pending (marker file)

    The script will be humanized and marked for your approval.
    After editing, approve it to proceed to design/build.
    """
    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        console.print(f"[bold red]Error:[/] config.yaml not found in {project_dir}")
        raise typer.Exit(1)

    try:
        config = load_config(config_path)
    except Exception as e:
        console.print(f"[bold red]Config error:[/] {e}")
        raise typer.Exit(1)

    from narrascape.cache import BuildCache
    from narrascape.stages.base import StageContext
    from narrascape.stages.write import WriteStage

    stage = WriteStage(
        llm_client=_get_llm_client(config=config),
        topic=topic or config.project.title,
        segment_count=segments,
        style=style,
        research_report=research_report or "",
        auto_humanize=not skip_humanize,
    )
    context = StageContext(
        config=config,
        script=_empty_script(),
        cache=BuildCache(config.pipeline_dir / ".cache"),
        state={},
        dry_run=False,
    )

    result = stage.run(context)
    if not result.success:
        console.print(f"[bold red]Write failed:[/] {result.message}")
        raise typer.Exit(1)


# ═══════════════════════════════════════════
# Humanize command
# ═══════════════════════════════════════════


@app.command("humanize")
def humanize_cmd(
    project_dir: Annotated[
        Path,
        typer.Option(
            "--project", "-p", help="Project directory", exists=True, file_okay=False, dir_okay=True
        ),
    ] = Path("."),
    aggressive: Annotated[
        bool, typer.Option("--aggressive", "-a", help="Aggressive mode (more changes)")
    ] = False,
    score_only: Annotated[
        bool, typer.Option("--score", help="Only score AI-likeness, don't modify")
    ] = False,
) -> None:
    """Remove AI writing patterns from an existing script.

    Backs up the original script and applies humanization patterns.
    """
    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        console.print(f"[bold red]Error:[/] config.yaml not found in {project_dir}")
        raise typer.Exit(1)

    try:
        config = load_config(config_path)
    except Exception as e:
        console.print(f"[bold red]Config error:[/] {e}")
        raise typer.Exit(1)

    from narrascape.cache import BuildCache
    from narrascape.stages.base import StageContext
    from narrascape.stages.humanize import HumanizeStage

    stage = HumanizeStage(
        llm_client=_get_llm_client(config=config), aggressive=aggressive, score_only=score_only
    )
    context = StageContext(
        config=config,
        script=_load_script_or_empty(config),
        cache=BuildCache(config.pipeline_dir / ".cache"),
        state={},
        dry_run=False,
    )

    result = stage.run(context)
    if not result.success:
        console.print(f"[bold red]Humanize failed:[/] {result.message}")
        raise typer.Exit(1)


# ═══════════════════════════════════════════
# Approve command
# ═══════════════════════════════════════════


@app.command("approve")
def approve_cmd(
    project_dir: Annotated[
        Path,
        typer.Option(
            "--project", "-p", help="Project directory", exists=True, file_okay=False, dir_okay=True
        ),
    ] = Path("."),
    stage: Annotated[
        str | None,
        typer.Option("--stage", "-s", help="Stage name to approve (omit to approve script)"),
    ] = None,
    message: Annotated[
        str | None, typer.Option("--message", "-m", help="Approval message (script approval only)")
    ] = None,
    notes: Annotated[
        str | None, typer.Option("--notes", "-n", help="Approval notes (stage approval only)")
    ] = None,
) -> None:
    """Approve a pending script or pipeline stage.

    Without --stage: copies scripts/script.yaml to scripts/script_approved.yaml
    and removes the .approval_pending marker.
    With --stage: approves a completed pipeline stage via PipelineApproval.
    """
    if stage:
        # Stage approval
        stage = _validated_stage_name(stage)
        config_path = project_dir / "config.yaml"
        if not config_path.exists():
            console.print(f"[bold red]Error:[/] config.yaml not found in {project_dir}")
            raise typer.Exit(1)
        try:
            config = load_config(config_path)
        except Exception as e:
            console.print(f"[bold red]Config error:[/] {e}")
            raise typer.Exit(1)
        ApprovalService(config).approve(stage, reviewer="human", notes=notes or "")
        console.print(f"[bold green]Stage '{stage}' approved[/]")
        console.print(
            f"[dim]  You can now continue the pipeline: narrascape build -p {project_dir}[/]"
        )
        return

    # Script approval
    scripts_dir = project_dir / "scripts"
    script_path = scripts_dir / "script.yaml"
    approved_path = scripts_dir / "script_approved.yaml"
    marker_path = project_dir / ".approval_pending"

    if not script_path.exists():
        console.print(f"[bold red]Error:[/] Script not found: {script_path}")
        raise typer.Exit(1)

    atomic_copy_file(script_path, approved_path)

    if marker_path.exists():
        marker_path.unlink()

    console.print("[bold green]Script approved![/]")
    console.print(f"  [cyan]→[/] {approved_path}")
    if message:
        console.print(f"  [dim]Message: {message}[/]")
    console.print(f"\n[bold]Next step:[/] narrascape design -p {project_dir}")


# ═══════════════════════════════════════════
# Pre-production command (Character & Environment References + Storyboard)
# ═══════════════════════════════════════════


@app.command("pre_production")
def pre_production_cmd(
    project_dir: Annotated[
        Path,
        typer.Option(
            "--project", "-p", help="Project directory", exists=True, file_okay=False, dir_okay=True
        ),
    ] = Path("."),
    style: Annotated[str, typer.Option("--style", "-s", help="Global image style prefix")] = "",
    dry_run: Annotated[
        bool, typer.Option("--dry-run", "-n", help="Preview without generating images")
    ] = False,
    llm_api_key: Annotated[
        str | None, typer.Option("--llm-api-key", help="LLM API key for character/scene extraction")
    ] = None,
    skip_turns: Annotated[
        bool, typer.Option("--skip-turns", help="Skip character turn-view generation")
    ] = False,
    skip_expressions: Annotated[
        bool, typer.Option("--skip-expressions", help="Skip character expression generation")
    ] = False,
    skip_storyboard: Annotated[
        bool, typer.Option("--skip-storyboard", help="Skip storyboard generation")
    ] = False,
) -> None:
    """Run visual pre-production: character references, environment references, and storyboard.

    Generates:
    - assets/references/character_*.png (character reference sheets)
    - assets/references/scene_*.png (environment reference images)
    - assets/storyboard/ (storyboard images if generated)
    - pipeline/pre_production.yaml (metadata for DesignStage)

    Uses AI Assistant bridge tasks for intelligent character/scene extraction.
    No external API keys needed when running with an AI assistant.
    """
    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        console.print(f"[bold red]Error:[/] config.yaml not found in {project_dir}")
        raise typer.Exit(1)

    try:
        config = load_config(config_path)
    except Exception as e:
        console.print(f"[bold red]Config error:[/] {e}")
        raise typer.Exit(1)

    script_path = project_dir / config.project.script_file
    if not script_path.exists():
        console.print(f"[bold red]Error:[/] Script not found: {script_path}")
        raise typer.Exit(1)

    console.print(f"[bold green]🎬 Pre-Production[/] for: [bold]{config.project.title}[/]")

    import yaml

    script_data = yaml.safe_load(script_path.read_text(encoding="utf-8"))
    segment_count = len(script_data.get("segments", []))
    console.print(f"  Script: {segment_count} segments")

    if dry_run:
        console.print(
            "[bold cyan]Dry run[/] — would extract characters/scenes and generate reference images"
        )
        return

    # Build LLM client (AI Assistant is built-in, no API keys needed)
    llm_client = _get_llm_client(llm_api_key, config=config)
    console.print("[dim]Using AI Assistant bridge for character/scene extraction and storyboard[/]")

    # Build and run pre-production stage
    from narrascape.stages.pre_production import PreProductionStage

    stage = PreProductionStage(
        llm_client=llm_client,
        style_template=style,
        generate_turns=not skip_turns,
        generate_expressions=not skip_expressions,
        generate_storyboard=not skip_storyboard,
    )
    from narrascape.cache import BuildCache
    from narrascape.stages.base import StageContext

    context = StageContext(
        config=config,
        script=load_script(config.script_path),
        cache=BuildCache(config.pipeline_dir / ".cache"),
        state={},
        dry_run=False,
    )

    result = stage.run(context)

    if result.success:
        console.print("[bold green]✅ Pre-production complete[/]")
        console.print(f"  Characters: {result.metadata.get('character_count', 0)}")
        console.print(f"  Scenes: {result.metadata.get('scene_count', 0)}")
        console.print(f"  Storyboard frames: {result.metadata.get('storyboard_frames', 0)}")
        console.print(f"  Report: {_pre_production_report_output(result.outputs)}")
    else:
        console.print(f"[bold red]❌ Pre-production failed:[/] {result.message}")
        raise typer.Exit(1)


# ═══════════════════════════════════════════
# Design command (AI Director)
# ═══════════════════════════════════════════


@app.command("design")
def design_cmd(
    project_dir: Annotated[
        Path,
        typer.Option(
            "--project", "-p", help="Project directory", exists=True, file_okay=False, dir_okay=True
        ),
    ] = Path("."),
    style: Annotated[
        str,
        typer.Option(
            "--style", "-s", help="Global image style prefix (e.g. 'oil painting, 19th century')"
        ),
    ] = "",
    dry_run: Annotated[
        bool, typer.Option("--dry-run", "-n", help="Preview design without writing files")
    ] = False,
    review: Annotated[
        bool, typer.Option("--review", "-r", help="Open design report for review before proceeding")
    ] = False,
    auto_approve: Annotated[
        bool,
        typer.Option(
            "--auto-approve", "-a", help="Auto-approve pending scripts without human review"
        ),
    ] = False,
    llm_api_key: Annotated[
        str | None,
        typer.Option(
            "--llm-api-key",
            help="OpenAI API key for PromptDirector (or set OPENAI_API_KEY env/.env)",
        ),
    ] = None,
) -> None:
    """Run AI director to design shots from narration script.

    Generates:
    - image_prompts.yaml (shot types + image prompts)
    - image_map.yaml (segment → image mapping)
    - design_report.yaml (full reasoning for human review)

    Uses AI Assistant bridge tasks for autonomous cinematic design via PromptDirector.
    No external API keys needed when running with an AI assistant.
    """
    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        console.print(f"[bold red]Error:[/] config.yaml not found in {project_dir}")
        raise typer.Exit(1)

    try:
        config = load_config(config_path)
    except Exception as e:
        console.print(f"[bold red]Config error:[/] {e}")
        raise typer.Exit(1)

    script_path = project_dir / config.project.script_file
    if not script_path.exists():
        console.print(f"[bold red]Error:[/] Script not found: {script_path}")
        raise typer.Exit(1)

    # Check for approval (with auto-approve option)
    approved_path = project_dir / "scripts" / "script_approved.yaml"
    marker_path = project_dir / ".approval_pending"
    if marker_path.exists() and not approved_path.exists():
        if auto_approve:
            atomic_copy_file(script_path, approved_path)
            marker_path.unlink()
            console.print("[bold green]✅ Auto-approved script[/]")
        else:
            console.print("[bold yellow]⚠️ Script pending approval![/]")
            console.print(f"  Please review and edit: {script_path}")
            console.print(f"  Then run: [bold]narrascape approve -p {project_dir}[/]")
            console.print(f"  Or use: [bold]narrascape design -p {project_dir} --auto-approve[/]")
            raise typer.Exit(1)

    console.print(
        f"[bold green]🎬 AI Director[/] designing shots for: [bold]{config.project.title}[/]"
    )

    # Read script
    import yaml

    script_data = yaml.safe_load(script_path.read_text(encoding="utf-8"))
    segment_count = len(script_data.get("segments", []))
    console.print(f"  Script: {segment_count} segments")

    if dry_run:
        console.print(
            f"[bold cyan]Dry run[/] — would analyze {segment_count} segments and generate design files"
        )
        return

    # Build LLM client (AI Assistant is built-in, no API keys needed)
    llm_client = _get_llm_client(llm_api_key, config=config)
    console.print("[dim]Using PromptDirector (AI Assistant bridge mode)[/]")

    # Build and run design stage
    from narrascape.stages.design import DesignStage

    stage = DesignStage(llm_client=llm_client, style_template=style)
    from narrascape.cache import BuildCache
    from narrascape.stages.base import StageContext

    context = StageContext(
        config=config,
        script=load_script(config.script_path),
        cache=BuildCache(config.pipeline_dir / ".cache"),
        state={},
        dry_run=False,
    )

    result = stage.run(context)

    if result.success:
        console.print("[bold green]✅ Design complete[/]")
        console.print(f"  Outputs: {result.outputs}")
    else:
        console.print(f"[bold red]❌ Design failed:[/] {result.message}")
        raise typer.Exit(1)


@app.command("build")
def build_cmd(
    project_dir: Annotated[
        Path,
        typer.Option(
            "--project", "-p", help="Project directory", exists=True, file_okay=False, dir_okay=True
        ),
    ] = Path("."),
    stages: Annotated[
        list[str] | None, typer.Option("--stage", help="Specific stages to run")
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Ignore cache and rebuild")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview without executing")] = False,
    parallel: Annotated[
        int, typer.Option("--parallel", help="Max parallel workers", min=1, max=16)
    ] = 4,
    interactive: Annotated[
        bool, typer.Option("--interactive", "-i", help="Pause after each stage for human review")
    ] = False,
    auto_approve: Annotated[
        bool, typer.Option("--approve", "-a", help="Auto-approve all stages (non-interactive)")
    ] = False,
    profile: Annotated[
        str,
        typer.Option(
            "--profile",
            help=f"Runtime build profile, e.g. {PRODUCTION_PROFILE_NAME}",
        ),
    ] = "",
    production: Annotated[
        bool,
        typer.Option(
            "--production",
            help=(
                "Use the production AI-film profile: seedream images, seedance video, "
                "oil painting style, strict director mode, and prep quality gates"
            ),
        ),
    ] = False,
) -> None:
    """Build the complete video pipeline.

    By default, runs non-interactively. Use --interactive to pause after each stage
    for human review, or --approve to auto-approve all stages without stopping.
    """
    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        console.print(f"[bold red]Error:[/] config.yaml not found in {project_dir}")
        raise typer.Exit(1)

    try:
        config = load_config(config_path)
        config = _apply_build_profile(config, profile=profile, production=production)
    except Exception as e:
        console.print(f"[bold red]Config error:[/] {e}")
        raise typer.Exit(1)

    if dry_run:
        console.print(f"[bold cyan]Dry run[/] — would build pipeline for {config.project.name}")
        return

    if interactive and auto_approve:
        console.print(
            "[bold yellow]Warning:[/] --interactive and --approve are mutually exclusive. Using --interactive."
        )
        auto_approve = False

    if interactive:
        console.print(
            "[bold yellow]🎬 Interactive Mode[/] — Pipeline will pause after each stage for human review."
        )
    elif auto_approve:
        console.print(
            "[bold dim]🤖 Auto-Approve Mode[/] — All stages will be approved automatically."
        )
    else:
        console.print(
            "[bold cyan]⚡ Non-Interactive Mode[/] — Stages will pause after completion for review."
        )
        console.print(
            "[dim]  Use --interactive to review in real-time, or --approve to skip reviews."
        )
        console.print(
            "[dim]  You can also approve individual stages later: narrascape approve -p . -s <stage>"
        )

    with _temporary_env("NARRASCAPE_KENBURNS_WORKERS", str(parallel)):
        results = PipelineRunService(
            config,
            pipeline_options={
                "dry_run": dry_run,
                "force": force,
                "interactive": interactive,
                "auto_approve": auto_approve,
                "console": console,
                "llm_client": _get_llm_client(config=config),
                "minimax_api_key": APIKeys.minimax(),
            },
        ).run(stages)

    # Print summary
    table = Table(title="Build Results")
    table.add_column("Stage", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Message")

    for stage_name, result in results.items():
        status = "✅" if result.success else "❌"
        table.add_row(stage_name, status, result.message)

    console.print(table)

    if all(r.success for r in results.values()):
        console.print("[bold green]✅ Build complete[/]")
        for stage_name, result in results.items():
            if isinstance(result.outputs, dict):
                for key, path in result.outputs.items():
                    console.print(f"  [dim]{key}:[/] {path}")
    else:
        failed = [name for name, r in results.items() if not r.success]
        console.print(f"[bold red]❌ Build stopped:[/] {', '.join(failed)}")
        console.print("[dim]  Review pending approvals: narrascape status -p .[/]")
        raise typer.Exit(1)


@app.command("status")
def status_cmd(
    project_dir: Annotated[
        Path,
        typer.Option(
            "--project", "-p", help="Project directory", exists=True, file_okay=False, dir_okay=True
        ),
    ] = Path("."),
) -> None:
    """Show pipeline status including approval states for a project."""
    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        console.print(f"[bold red]Error:[/] config.yaml not found in {project_dir}")
        raise typer.Exit(1)

    try:
        config = load_config(config_path)
    except Exception as e:
        console.print(f"[bold red]Config error:[/] {e}")
        raise typer.Exit(1)

    from narrascape.pipeline import PipelineState

    state = PipelineState(config.pipeline_dir / "state.json")

    from narrascape.pipeline_approval import PipelineApproval

    approval = PipelineApproval(config.pipeline_dir)

    # ── Pipeline stages table ──
    table = Table(title=f"Pipeline Status: {config.project.name}")
    table.add_column("Stage", style="cyan")
    table.add_column("Execution", style="green")
    table.add_column("Approval", style="yellow")

    for stage_name in _status_stage_names():
        exec_status = state.get_stage_status(stage_name)
        exec_emoji = (
            "✅" if exec_status == "completed" else "⏳" if exec_status == "pending" else "❌"
        )

        appr_status = approval.get_status(stage_name)
        appr_emoji = {
            "approved": "✅",
            "pending": "⏳",
            "rejected": "❌",
            "skipped": "⏭️",
            "unknown": "—",
        }.get(appr_status, "—")

        table.add_row(stage_name, f"{exec_emoji} {exec_status}", f"{appr_emoji} {appr_status}")

    console.print(table)

    # ── Approval summary ──
    all_approvals = approval.list_all()
    pending = [s for s, st in all_approvals.items() if st == "pending"]
    rejected = [s for s, st in all_approvals.items() if st == "rejected"]

    if pending:
        console.print()
        console.print(f"[bold yellow]⏳ Pending Reviews ({len(pending)}):[/]")
        for stage_name in pending:
            console.print(f"  narrascape approve -p . -s {stage_name}")
    if rejected:
        console.print()
        console.print(f"[bold red]❌ Rejected Stages ({len(rejected)}):[/]")
        for stage_name in rejected:
            console.print(f"  {stage_name}")
        console.print("[dim]  Fix and retry: narrascape build -p . --stage <stage> --force[/]")
    from narrascape.dashboard_data import load_rework_loop_summary

    loop = load_rework_loop_summary(config.pipeline_dir)
    console.print()
    loop_table = Table(title="Rework Loop")
    loop_table.add_column("Metric", style="cyan")
    loop_table.add_column("Value", style="white")
    loop_table.add_row("Status", str(loop.get("status", "not_started")))
    loop_table.add_row("Supervisor", str(loop.get("supervisor_status", "missing")))
    loop_table.add_row("Rework actions", str(loop.get("action_count", 0)))
    loop_table.add_row("Executed actions", str(loop.get("executed_count", 0)))
    loop_table.add_row("QA errors", str(loop.get("qa_error_count", 0)))
    loop_table.add_row("Visual findings", str(loop.get("visual_finding_count", 0)))
    next_stages = loop.get("next_stages") or []
    loop_table.add_row("Next stages", " -> ".join(next_stages) if next_stages else "-")
    console.print(loop_table)


@app.command("clean")
def clean_cmd(
    project_dir: Annotated[
        Path,
        typer.Option(
            "--project", "-p", help="Project directory", exists=True, file_okay=False, dir_okay=True
        ),
    ] = Path("."),
    all: Annotated[bool, typer.Option("--all", help="Clean everything")] = False,
    stage: Annotated[str | None, typer.Option("--stage", help="Specific stage to clean")] = None,
) -> None:
    """Clean pipeline artifacts."""
    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        console.print(f"[bold red]Error:[/] config.yaml not found in {project_dir}")
        raise typer.Exit(1)

    try:
        config = load_config(config_path)
    except Exception as e:
        console.print(f"[bold red]Config error:[/] {e}")
        raise typer.Exit(1)

    if all:
        PipelineRunService(config).clean_all()
        console.print("[bold green]✅ Cleaned all pipeline artifacts[/]")
    elif stage:
        if stage == ".cache":
            PipelineRunService(config).clean_cache()
        else:
            PipelineRunService(config).clean_stage(_validated_stage_name(stage))
        console.print(f"[bold green]✅ Cleaned {stage}[/]")
    else:
        console.print("[bold yellow]Use --all or --stage <name>[/]")


@app.command("reject")
def reject_cmd(
    stage: Annotated[str, typer.Option("--stage", "-s", help="Stage name to reject")],
    project_dir: Annotated[
        Path,
        typer.Option(
            "--project", "-p", help="Project directory", exists=True, file_okay=False, dir_okay=True
        ),
    ] = Path("."),
    notes: Annotated[str | None, typer.Option("--notes", "-n", help="Rejection notes")] = None,
) -> None:
    """Reject a pipeline stage. Requires fixing and re-running."""
    stage = _validated_stage_name(stage)
    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        console.print(f"[bold red]Error:[/] config.yaml not found in {project_dir}")
        raise typer.Exit(1)

    try:
        config = load_config(config_path)
    except Exception as e:
        console.print(f"[bold red]Config error:[/] {e}")
        raise typer.Exit(1)

    ApprovalService(config).reject(stage, reviewer="human", notes=notes or "")
    console.print(f"[bold red]❌ Stage '{stage}' rejected[/]")
    console.print(
        f"[dim]  Fix the issue, then run: narrascape build -p . --stage {stage} --force[/]"
    )


@app.command("skip")
def skip_cmd(
    stage: Annotated[str, typer.Option("--stage", "-s", help="Stage name to skip")],
    project_dir: Annotated[
        Path,
        typer.Option(
            "--project", "-p", help="Project directory", exists=True, file_okay=False, dir_okay=True
        ),
    ] = Path("."),
    notes: Annotated[str | None, typer.Option("--notes", "-n", help="Skip notes")] = None,
) -> None:
    """Skip a pipeline stage (mark as approved without review)."""
    stage = _validated_stage_name(stage)
    config_path = project_dir / "config.yaml"
    if not config_path.exists():
        console.print(f"[bold red]Error:[/] config.yaml not found in {project_dir}")
        raise typer.Exit(1)

    try:
        config = load_config(config_path)
    except Exception as e:
        console.print(f"[bold red]Config error:[/] {e}")
        raise typer.Exit(1)

    ApprovalService(config).skip(stage, reviewer="human", notes=notes or "")
    console.print(f"[bold dim]⏭️ Stage '{stage}' skipped[/]")
    console.print("[dim]  You can now continue the pipeline: narrascape build -p .[/]")


@app.command("version")
def version_cmd() -> None:
    """Show version."""
    console.print(f"narrascape version {__version__}")


def main() -> None:
    """Installed console-script entry point."""
    app()


if __name__ == "__main__":
    main()
