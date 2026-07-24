# Narrascape（中文文档）

Narrascape 是一个开源的 AI 影视制作流水线，面向旁白驱动的影片、纪录片、解说片和故事视频。

它不是一个"输入一句话就生成视频"的按钮。Narrascape 把剧本变成一部**每个镜头都可检查、可审核、可复现**的 AI 影片——一座开源的小型 AI 制片厂。

## 为什么存在

大多数 AI 视频工作流会在"连续性"上翻车：同一个角色、同一件衣服、同一个房间、同一条情绪曲线，以及剪得在一起的镜头。Narrascape 把这些要求从提示词里的玄学，变成落在磁盘上的制作产物（artifact）。

核心思路是：

```text
创意指导 -> 可执行契约 -> 生成/真实素材 -> 影片时间线 -> QA -> 返工
```

每个主要阶段都会写出可以查看、修改、测试和重跑的文件。

## 核心功能：五大支柱

1. **契约化 AI 导演**：`director_contract.yaml` 为每个镜头写下故事意图、镜头语言、连续性锁、QA 断言和 prompt 蓝图——导演的创意判断必须落成可执行契约，而不是停留在一段提示词。
2. **连续性工程**：分镜首帧条件（`video.storyboard_conditioning`）、参考图注入、continuity bible、多 take 生成，让角色脸、服装、场景跨镜头稳定。
3. **人工审核工作流**：逐阶段审批门（approve / reject）、take 四信号质量评分、MCTS 选 take 的完整决策轨迹、QA 六维度分类、prompt_safety 提示词安全审计。
4. **成本与可靠性工程**：`video_tasks.json` 任务台账支持断点续跑、请求指纹缓存保证不重复扣费、成本台账 `cost_report.yaml` 连失败也记账、预算 cap、Retry-After / 限流 / 熔断 HTTP 中间件。
5. **AI 助手接管协议**：bridge 模式让外部 AI 助手充当 LLM，`assistant_handoff` 写出机器可读的接管包，让 Codex 这类助手不靠猜就能接手项目。

## 当前状态

Narrascape 是一个**早期 AI 制片厂原型**：管线是真实可用的，工程质量扎实——622 个测试全部通过，CI 覆盖 Ubuntu 与 Windows 双系统、Python 3.10 / 3.11 / 3.12，mypy 以 strict 模式检查——但最终的创意质量仍然取决于你配置的 LLM、媒体 provider、素材质量和人工审核的认真程度。

已经实现的生产向特性（节选）：

- AI 导演阶段群：剧本结构、导演契约、连续性、剪辑审查、创意审查、视觉语义 QA、影片监制。
- `film_timeline.yaml` 作为默认剪辑主线；视觉优先级为生成视频 → 真实素材 → 生成图片兜底。
- Seedream 生图、Seedance 生视频，经 provider selector 进入执行层。
- 多 take 视频生成与 `take_select` 选 take（可选 MCTS 决策树策略）。
- 视频生成前的生产就绪门（production readiness）。
- 渲染 QA：文件有效性、音频、字幕、时长漂移、黑帧、重复镜头、缺失片段、占位图残留、连续性风险、节奏风险。
- `rework_execute` 消费返工计划：隔离失败片段、写重生成/重剪/换素材队列并触发重跑。
- 离线确定性 provider，用于端到端测试与无网络验证。

## 快速开始

从源码检出安装：

```bash
pip install -e ".[dev]"
narrascape init my-video
narrascape build -p my-video --approve
```

无网络冒烟测试，把 config.yaml 改成 local providers：

```yaml
llm:
  mode: none
images:
  provider: local
tts:
  provider: local
audio:
  music:
    provider: local
```

离线模式证明管线端到端是通的，但它不产出影视级创意质量。

## 人工审批工作流

Narrascape 的默认姿态是"每一步都要审核"：

- 不加 `--approve` 运行时，每完成一个阶段管线就会停下，并在 `pipeline/<project>/approvals/` 写入待审核标记。
- 用 `narrascape approve -p my-video -s design` 通过后重新运行 build，管线才会继续。
- 用 `narrascape reject -p my-video -s design --notes "修改人脸"` 打回，管线会停在该阶段直到问题解决。
- `--interactive` 会在每个阶段完成后于终端暂停，当场审核。
- `--approve` 自动通过所有阶段，适合 CI 和可信的本地构建。

打回重跑不会重复扣费：付费阶段只在"输出文件存在且请求指纹匹配"时才复用结果；指纹不匹配才重新生成。

## 常用命令

```bash
narrascape init my-video                                # 创建项目
narrascape build -p my-video                            # 逐阶段审核模式构建
narrascape build -p my-video --approve                  # 自动通过所有审批门
narrascape build -p my-video --interactive              # 每阶段终端暂停审核
narrascape build -p my-video --production --approve     # 生产模式（严格 profile）
narrascape build -p my-video --stage-parallel 4 --approve   # 依赖层内并行执行阶段
narrascape build -p my-video --stage generate_video --approve  # 只跑某个阶段（自动带上游依赖）
narrascape status -p my-video                           # 查看阶段状态
narrascape approve -p my-video -s design                # 通过某阶段
narrascape reject -p my-video -s design --notes "原因"  # 打回某阶段
narrascape clean -p my-video --all                      # 清理产物
narrascape dashboard                                    # 本地控制面板（可选依赖）
```

## 生产模式

```bash
narrascape build -p examples/golden-sample --production --approve
```

`--production` 应用 `seedream-seedance-oil-painting` profile：Seedream 生图、Seedance 生视频、油画风格、`pipeline.video_generation: required`、`pipeline.strict_director: true`、生产质量门、每镜头至少 3 个 take、最多 2 轮自动返工。

当你希望"AI 导演缺席、前期准备不足、生成视频缺失"这类问题尽早失败、而不是悄悄退回兜底路径时，使用生产模式。

## Provider 矩阵

| 领域 | 已实现路径 |
| --- | --- |
| LLM | AI 助手 bridge、文件 bridge、OpenAI 兼容 API、Anthropic、DeepSeek、Volcengine、本地 HTTP |
| 图像 | Seedream、本地占位图 |
| 视频 | Seedance 异步图生视频 |
| TTS | MiniMax、本地蜂鸣 provider |
| 音乐 | MiniMax、本地蜂鸣 provider |
| 真实素材 | 本地素材库、footage 时间线、粗剪渲染 |
| 预览/渲染 | Remotion 时间线交接、FFmpeg 拼接 |
| QA | ffprobe 驱动的渲染与质量检查 |

## 文档导航

- [中文快速上手](docs/quickstart.zh-CN.md)
- [产品介绍（中英双语）](docs/product-introduction.md)
- [English README](README.md)
- [完整功能地图（英文）](docs/features.md)
- [配置参考（英文）](docs/config-reference.md)
- [架构（英文）](docs/architecture.md)
- [文档总目](docs/index.md)

## 黄金样片

[examples/golden-sample](examples/golden-sample/README.md) 是固定的质量考卷：一段《罪与罚》室内短场景——一个房间、少量角色、明确的服装锁和分镜意图、6 个镜头。每次优化之后，它用来回答一个问题：

> 这次改动是真的产出了更可控的电影素材，还是只是管线又跑了一遍？

## 许可证

Narrascape 以 GNU Affero General Public License v3.0 发布，详见 [LICENSE](LICENSE)。
