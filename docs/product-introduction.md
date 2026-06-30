# Narrascape Product Introduction / 产品介绍

## 中文介绍

Narrascape 是一个面向 AI 电影、纪录片、解说片和叙事视频的开源制作流水线。它的目标不是把一段文字直接丢给视频模型，也不是简单地把图片拼成视频，而是把影视制作中的关键步骤拆成可检查、可复用、可自动化的工程产物。

它把一部视频拆成这些环节：

```text
剧本 -> 视觉前期 -> AI 导演设计 -> 分镜和导演合同
-> 生图 / 生视频 / 真实素材 -> film_timeline.yaml
-> 预览 -> 拼接 -> 配音和音乐 -> 字幕 -> QA -> 返工
```

换句话说，Narrascape 更像一个小型 AI 制片厂，而不是一个生成按钮。

## 项目愿景

AI 视频真正难的地方不是生成一个漂亮片段，而是让多个镜头共同服务一个故事：

- 角色脸、年龄、衣物和体态要稳定。
- 场景、时代、光线和色彩要连续。
- 镜头需要有景别、机位、运动和情绪目的。
- 片段需要能剪到同一条时间线上。
- 失败镜头应该能被定位、重写、重生成或重剪。

Narrascape 的核心想法是：让大模型负责创意判断，但必须把创意落到可执行的合同里。这个合同包括提示词、分镜绑定、参考图、连续性锁、QA 条件和返工队列。

## 当前能力

Narrascape 目前已经具备一个早期 AI film studio prototype 的骨架：

- AI Director：从剧本拆解 act、scene、sequence 和 shot。
- Director Contract：为每个镜头生成故事目的、电影语言、连续性约束、分镜绑定、提示词蓝图、provider prompts、负面提示词和 QA 断言。
- Reference Plate：把角色图、场景图、风格图和故事板引用整理成每镜头参考包。
- Storyboard Sheet：生成可审查的故事板联系表。
- Animatic：在昂贵视频生成前先生成低成本节奏预览。
- Production Readiness：在生产模式下检查剧本密度、角色/场景/分镜覆盖、导演合同完整度、提示词蓝图和 QA 条件。
- Generate Images / Video：支持 Seedream 生图和 Seedance 生视频，并通过 provider selector 进入执行层。
- Multi-Take：关键镜头可以生成多个视频 take，再由 `take_select` 选择。
- Film Timeline：以 `film_timeline.yaml` 作为默认成片骨架。
- Source Media：支持真实素材扫描、素材清单和 footage timeline。
- QA：检查文件可播放性、黑帧、静音、字幕、时长偏差、镜头覆盖、缺失片段、重复镜头、占位图残留、连续性风险和叙事节奏风险。
- Rework Loop：把 QA 和导演审查转成 `rework_plan.yaml`，再由 `rework_execute` 执行重生成、重剪或换素材队列。

默认视觉优先级是：

```text
generated video -> source footage -> generated image fallback
```

这意味着项目已经从早期的 Ken Burns 图片动画路线，升级为 film timeline 主导的 AI 影视制作路线。

## 生产模式

生产模式用于减少“准备没做好就开始抽卡”的问题：

```bash
narrascape build -p examples/golden-sample --production --approve
```

`--production` 会应用 `seedream-seedance-oil-painting` profile：

- Seedream 生图。
- Seedance 生视频。
- 油画风格。
- `video_generation: required`。
- `strict_director: true`。
- `production_quality_gates: true`。
- 每个镜头至少 3 个 take。
- 最多 2 轮自动返工。

如果 AI 导演没有真正使用大模型，或者关键准备阶段不完整，生产模式会失败，而不是让本地 fallback 混进成片。

## 黄金样片

[examples/golden-sample](../examples/golden-sample/README.md) 是项目的固定质量考卷。它是一个《罪与罚》短场景：一个房间、少量角色、清晰服装锁定、明确故事板和 6 个镜头。

它用来回答一个问题：

> 优化之后，项目是否真的产出了更可控的电影素材，还是只是管线又跑了一遍？

后续每一次重要优化都应该能用这个样片验证。

## 和常见 AI 视频工具的区别

| 维度 | 常见 AI 视频工具 | Narrascape |
| --- | --- | --- |
| 输入 | 一段 prompt 或短剧本 | 结构化剧本、分镜、参考图、素材库、导演合同 |
| 导演控制 | 多停留在 prompt | 写入 `director_contract.yaml` 并被生成、QA、返工消费 |
| 时间线 | 工具内部隐藏 | `film_timeline.yaml` 可读、可改、可测试 |
| 视觉来源 | 主要依赖生成 | 生成视频、真实 footage、生成图 fallback 混合 |
| QA | 主要靠人工观看 | 文件、音频、字幕、黑帧、重复、覆盖率、连续性、节奏检查 |
| 返工 | 手动重试 | 生成返工计划并执行队列 |
| 开放性 | 多为封闭产品 | AGPL-3.0 开源，可扩展 stage 和 provider |

## 当前边界

Narrascape 仍然是早期原型。它已经具备完整制作管线、导演合同、film timeline、QA 和返工执行的工程骨架，但最终画面质量仍然取决于：

- 使用的大模型是否足够强。
- 生图和生视频 provider 的能力。
- 参考图质量。
- 剧本和故事板准备是否扎实。
- 人工审片和返工策略是否认真执行。

`llm.mode: none` 和 local providers 只用于离线验证。它们能证明项目流程打通，但不能代表电影级创意输出。

## 路线图

- 更强的视觉语义 QA：让模型真正检查角色脸、衣服、场景和构图是否符合导演合同。
- 更成熟的 multi-take 选择：结合 QA、LLM 判断和人工偏好选择最佳镜头。
- 更完整的 continuity bible：跨场景追踪角色、服装、灯光、轴线、地点状态。
- 更强的 source media 剪辑：让真实素材纪录片工作流更接近专业剪辑。
- 更丰富的 provider 接入：扩展视频、图像、声音、音乐和后期 provider。
- 更好的创作者界面：在 dashboard 中查看时间线、QA、返工队列和生产状态。

---

## English Introduction

Narrascape is an open-source AI film-production pipeline for narration-driven
films, documentaries, explainers, and story videos. It does not try to be a
single prompt-to-video button. It turns the production process into inspectable
artifacts: script, pre-production, AI Director design, storyboard-bound shot
contracts, generated or source media, timeline assembly, audio, subtitles, QA,
and rework.

## Vision

The hard part of AI video is not making one attractive clip. The hard part is
making many shots serve one story:

- stable character identity
- stable wardrobe
- stable locations and lighting
- clear camera language
- clips that cut together
- failed shots that can be regenerated, recut, or replaced

Narrascape lets an LLM make creative decisions, but those decisions must become
executable contracts: prompts, storyboard bindings, reference images,
continuity locks, QA assertions, and rework queues.

## Implemented Capabilities

- AI Director stages for screenplay structure, director contract, continuity,
  editing review, creative review, visual semantic QA, and film supervision.
- `director_contract.yaml` with story intent, film language, continuity locks,
  storyboard bindings, prompt blueprint, provider prompts, negative prompts,
  and QA assertions.
- `reference_plates.yaml` for per-shot style, character, scene, and storyboard
  reference handoff.
- Storyboard sheet and animatic stages before video generation.
- Production readiness gates for stricter AI-film builds.
- Seedream image generation and Seedance video generation through provider
  selection.
- Multi-take video generation and take selection.
- `film_timeline.yaml` as the default editorial spine.
- Optional source-media workflow for real footage.
- QA for playback validity, black frames, silence, subtitles, duration drift,
  coverage, missing clips, repeated shots, placeholder residue, continuity risk,
  and pacing risk.
- Executable rework loop through `rework_plan.yaml` and `rework_execute`.

The default visual priority is:

```text
generated video -> source footage -> generated image fallback
```

## Production Mode

Run the fixed quality benchmark with:

```bash
narrascape build -p examples/golden-sample --production --approve
```

`--production` applies the `seedream-seedance-oil-painting` profile:

- Seedream images.
- Seedance video.
- Oil-painting visual style.
- Required generated video.
- Strict director mode.
- Production readiness quality gates.
- At least three takes per shot.
- Up to two automatic rework cycles.

## Golden Sample

[examples/golden-sample](../examples/golden-sample/README.md) is the fixed
quality benchmark: a short *Crime and Punishment* chamber scene with one room,
a small cast, clear wardrobe locks, storyboard intent, and six shots.

It exists to answer:

> Did the pipeline produce better controllable film material, or did it only run?

## Boundaries

Narrascape is still an early AI film studio prototype. It has the production
graph, director artifacts, film timeline, QA, and rework execution skeleton, but
final creative quality still depends on the configured LLM, image/video
providers, reference material, and human review.

Offline mode proves the pipeline is wired end to end. It does not produce
film-grade imagery.
