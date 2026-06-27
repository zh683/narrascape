# Narrascape Product Introduction

## 发布状态 / Release Status

Narrascape is now published as a public GitHub repository at [zh683/narrascape](https://github.com/zh683/narrascape). The current `main` branch runs CI across Ubuntu and Windows with Python 3.10, 3.11, and 3.12.

Narrascape 目前已经作为公开 GitHub 仓库发布：[zh683/narrascape](https://github.com/zh683/narrascape)。当前 `main` 分支会在 Ubuntu 和 Windows 上使用 Python 3.10、3.11、3.12 跑完整 CI。

## 中文介绍

Narrascape 是一个面向 AI 电影、纪录片和叙事视频的开源制作流水线。它的目标不是只把一段文字变成一组图片，也不是只做简单的视频拼接，而是把“剧本 -> 导演设计 -> 分镜约束 -> 素材生成/选择 -> 时间线剪辑 -> 音频字幕 -> QA -> 返工”的完整制作链条变成可检查、可复用、可自动化的工程系统。

如果说普通 AI 视频工具更像一个生成按钮，Narrascape 更像一个小型 AI 制片厂。它会把创意拆成具体的 production artifacts：剧本结构、镜头设计、导演合同、连续性 bible、film timeline、剪辑评审、视觉语义 QA 和返工计划。每一步都有文件落地，用户可以审查、修改、重新运行，也可以接入自己的生成模型和本地素材库。

## 项目愿景

Narrascape 希望让个人创作者、小团队和研究者拥有一套可解释的 AI 影视生产系统。未来的目标是支持更长、更复杂、更有连续性的 AI 电影制作：角色稳定、服装稳定、场景稳定、镜头语言明确、剪辑节奏可控，并且能在失败时自动知道应该重生成、重剪，还是换素材。

它关注的是“可导演的 AI 生成”，而不是“不可控的随机生成”。大模型负责创意判断和导演思考，但最终要落到可以执行的视频提示词、故事板绑定、素材引用、QA 条件和返工队列里。

## 核心能力

- AI Director：把文案拆成 act、scene、sequence 和 shot，并生成镜头意图、电影语言、视频提示词、负面提示词和 QA 断言。
- Director Contract：把导演创意变成每个镜头的执行合同，绑定 storyboard frame、角色位置、场景引用、服装锁定、构图要求和参考图。
- Film Timeline：以 `film_timeline.yaml` 作为默认成片骨架，统一管理生成视频、真实素材、生成图片 fallback、音频、字幕和节奏信息。
- Video-First Assembly：优先使用 AI 生成视频，其次使用 source footage，最后才退回生成图片和轻量动画。
- Source Media Workflow：支持扫描本地素材，建立 asset manifest，并生成 footage timeline，用于真实素材纪录片剪辑。
- Cinematic QA：检查文件可播放、黑帧、静音、字幕、时长偏差、镜头覆盖率、缺失片段、重复镜头、低质量占位图残留、连续性风险和叙事节奏风险。
- Rework Loop：把 QA 和导演评审结果转成 `rework_plan.yaml`，并通过 `rework_execute` 将失败镜头加入重生成、重剪或换素材队列。
- Provider Governance：图像、TTS、音乐和视频生成不再只是配置项，而是通过 provider selector 进入执行层，并记录实际使用的 provider。
- LLM / Offline Dual Path：可以接入大模型进行创意导演，也可以在 `llm.mode: none` 下跑完整离线测试，证明流水线本身被打通。

## 制作流程

```text
script
  -> pre_production
  -> design
  -> screenplay_structure
  -> director_contract
  -> generate_images / generate_video / source_media
  -> film_timeline
  -> film_assemble
  -> generate_tts + generate_music + remix_audio
  -> audio
  -> subtitles
  -> qa
  -> continuity_bible
  -> editing_review
  -> director_review
  -> rework_plan
  -> creative_review
  -> visual_semantic_qa
  -> film_supervisor
  -> rework_execute
```

默认视觉优先级是：

```text
generated video -> source footage -> generated image fallback
```

这意味着 Narrascape 的方向已经从早期的 Ken Burns 图片动画，转向 film timeline 主导的电影制作流程。生成图片仍然有价值，但它更像备用视觉资产，而不是最终影片的唯一主体。

## 为什么它不只是模板系统

Narrascape 区分三件事：

- Prompt template：告诉 LLM 应该输出什么结构。
- LLM creative output：由大模型生成的镜头设计、导演判断、创意评审和语义 QA。
- Offline fallback：没有模型或没有网络时使用的确定性本地逻辑，主要用于测试和验证。

当配置了 LLM 模式时，AI Director 会把大模型的创意转成持久化文件，而不是只在一次 prompt 里消失。`director_contract.yaml` 会成为下游生成视频、时间线拼接、视觉 QA 和返工判断共同引用的执行依据。

## 适合谁

- 想把文案自动转成视频生产流程的 AI 创作者。
- 想研究 AI 影视工作流、agent stage 和可检查生成系统的开发者。
- 想把真实素材和生成素材混合剪辑的纪录片/解释视频团队。
- 想接入不同生成模型，并比较 provider 质量、成本和可靠性的工程团队。
- 想构建“AI 导演 + 自动剪辑 + QA 返工”系统的研究者。

## 当前边界

Narrascape 仍然是早期 AI film studio prototype。它已经具备完整流水线、导演合同、film timeline、视频拼接、source media、QA 和返工执行的骨架，但最终创意质量仍取决于所接入的大模型、视频生成模型、素材质量和人工审片。

离线模式可以证明流程打通，但不会生成真正的电影级画面。要获得更好的实际成片，需要配置真实 LLM、图像、视频、TTS 和音乐 provider，并持续通过 QA 和导演返工循环迭代。

## 与传统 AI 视频工具的区别

| 维度 | 常见 AI 视频工具 | Narrascape |
| --- | --- | --- |
| 输入方式 | 一段 prompt 或短脚本 | 结构化剧本、分镜、故事板、参考图和素材库 |
| 导演控制 | 多数停留在 prompt | 生成 `director_contract.yaml` 并进入执行和 QA |
| 时间线 | 工具内部不可见 | `film_timeline.yaml` 可读、可改、可测试 |
| 素材来源 | 主要依赖生成 | 生成视频、真实 footage、图片 fallback 混合 |
| QA | 依赖人工观看 | 文件、音频、字幕、黑帧、重复、覆盖率、节奏和连续性检查 |
| 返工 | 手动重试 | 生成 rework plan，并可执行重生成/重剪/换素材队列 |
| 开放性 | 常为封闭产品 | AGPL-3.0 开源，可扩展 stage 和 provider |

## Roadmap

- 更强的视觉语义 QA：让模型真正看懂角色、场景、服装和构图是否符合 director contract。
- 更成熟的多 take 选择：为关键镜头生成多个候选版本，由 QA 和 LLM 共同选择。
- 更完整的 continuity bible：持续维护角色外观、衣物、灯光、轴线和场景状态。
- 更强的 source media 剪辑：让真实素材纪录片工作流更加接近专业剪辑流程。
- 更丰富的 provider 接入：扩展更多视频、图像、声音和剪辑后期 provider。
- 更好的创作者界面：通过 dashboard 展示 pipeline、时间线、QA 报告和返工队列。

---

## English Introduction

Narrascape is an open-source production pipeline for AI films, documentaries, and narration-driven videos. Its goal is not to turn text into a few images or simply concatenate generated clips. It turns the full production chain into an inspectable engineering system: script, director design, shot contracts, media generation or selection, timeline assembly, audio, subtitles, QA, and rework.

Most AI video tools behave like a generation button. Narrascape is closer to a small AI production studio. It turns creative intent into durable production artifacts: screenplay structure, shot design, director contracts, continuity bible, film timeline, editing review, visual semantic QA, and rework plans. Every step is written to disk, so it can be reviewed, edited, rerun, tested, and extended.

## Vision

Narrascape aims to give solo creators, small teams, and researchers an explainable AI film-production system. The long-term goal is to support longer, more complex, more continuous AI films: stable characters, stable wardrobe, stable locations, clear shot language, controllable pacing, and automatic rework decisions when a shot fails.

The core idea is directable AI generation. LLMs can provide creative judgment and director-level reasoning, but that reasoning must become executable prompts, storyboard bindings, source-media references, QA assertions, and rework queues.

## Core Capabilities

- AI Director: decomposes narration into acts, scenes, sequences, and shots, then creates shot intent, film language, video prompts, negative prompts, and QA assertions.
- Director Contract: turns director intent into per-shot execution contracts with storyboard frame ids, character positions, scene references, wardrobe locks, composition requirements, and reference images.
- Film Timeline: uses `film_timeline.yaml` as the default production spine for generated video, source footage, generated-image fallback, audio, subtitles, and pacing metadata.
- Video-First Assembly: prefers generated video, falls back to source footage, and uses generated images only when stronger visual material is unavailable.
- Source Media Workflow: scans local footage, writes an asset manifest, and builds a footage timeline for documentary-style editing.
- Cinematic QA: checks playback validity, black frames, silence, subtitles, duration drift, shot coverage, missing clips, repeated shots, placeholder residue, continuity risk, and pacing risk.
- Rework Loop: turns QA and director findings into `rework_plan.yaml`, then `rework_execute` queues shots for regeneration, recut, or source-media replacement.
- Provider Governance: image, TTS, music, and video generation are selected by the provider selector at execution time and recorded in stage state.
- LLM / Offline Dual Path: real creative work can use an LLM, while `llm.mode: none` keeps the full pipeline testable offline.

## Production Flow

```text
script
  -> pre_production
  -> design
  -> screenplay_structure
  -> director_contract
  -> generate_images / generate_video / source_media
  -> film_timeline
  -> film_assemble
  -> generate_tts + generate_music + remix_audio
  -> audio
  -> subtitles
  -> qa
  -> continuity_bible
  -> editing_review
  -> director_review
  -> rework_plan
  -> creative_review
  -> visual_semantic_qa
  -> film_supervisor
  -> rework_execute
```

The default visual priority is:

```text
generated video -> source footage -> generated image fallback
```

Narrascape has moved away from a Ken Burns-first image animation workflow toward a film timeline-first production workflow. Generated images are still useful, but they are fallback visual assets rather than the only path to a finished video.

## Why It Is Not Just Templates

Narrascape separates three layers:

- Prompt templates: instructions that tell an LLM what structured output to return.
- LLM creative output: model-generated shot design, director judgment, creative review, and semantic QA.
- Offline fallback: deterministic local logic used when no model or network is available.

When an LLM mode is configured, the AI Director turns model creativity into durable artifacts instead of losing it inside one prompt call. `director_contract.yaml` becomes the shared execution contract for video generation, timeline assembly, visual QA, and rework planning.

## Who It Is For

- AI creators who want to turn narration into a production workflow.
- Developers studying AI film pipelines, agent stages, and inspectable generation systems.
- Documentary and explainer teams mixing generated media with real footage.
- Engineering teams comparing provider quality, cost, control, and reliability.
- Researchers building AI director, automatic editing, QA, and rework systems.

## Current Boundaries

Narrascape is still an early AI film studio prototype. It already has the skeleton for a full production pipeline, director contracts, film timeline assembly, source media, cinematic QA, and executable rework. The final creative quality still depends on the configured LLM, video model, media providers, source footage, and human review.

Offline mode proves the pipeline is wired end to end, but it does not produce film-grade imagery. For stronger real-world output, configure real LLM, image, video, TTS, and music providers, then iterate through QA and director rework loops.

## How It Differs From Typical AI Video Tools

| Dimension | Typical AI Video Tools | Narrascape |
| --- | --- | --- |
| Input | One prompt or short script | Structured script, shots, storyboard, references, and media library |
| Director control | Mostly prompt-level | `director_contract.yaml` reaches generation and QA |
| Timeline | Hidden inside the tool | `film_timeline.yaml` is readable, editable, and testable |
| Media sources | Mostly generated media | Generated video, source footage, and image fallback |
| QA | Mostly human review | Playback, audio, subtitles, black frames, repetition, coverage, pacing, and continuity checks |
| Rework | Manual retry | Rework plans and executable regeneration, recut, and replacement queues |
| Openness | Often closed product | AGPL-3.0 open source, extensible stages and providers |

## Roadmap

- Stronger visual semantic QA that can truly judge whether characters, locations, wardrobe, and composition match the director contract.
- Better multi-take selection where key shots generate multiple candidates and QA plus LLM review choose the best take.
- Deeper continuity bible tracking for character appearance, wardrobe, lighting, screen axis, and location state.
- More complete source-media editing for professional documentary workflows.
- More provider integrations for video, image, voice, music, editing, and finishing.
- A richer creator dashboard for pipeline status, timeline review, QA reports, and rework queues.
