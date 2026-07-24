# 快速上手（中文）

这份指南带你从安装跑到第一条完整视频，并说明什么时候该从离线验证切换到真实 AI provider。英文版见 [Quick Start](quickstart.md)，项目总览见 [中文 README](../README.zh-CN.md)。

## 1. 环境准备

- **Python 3.10+**（CI 实际覆盖 3.10 / 3.11 / 3.12）。
- **ffmpeg 必备**：视频拼接、抽帧和 QA 都依赖 `ffmpeg` / `ffprobe`，必须能在 PATH 中找到。
  - Windows：`winget install ffmpeg` 或 `choco install ffmpeg`，装完重开终端。
  - Ubuntu / Debian：`sudo apt-get install ffmpeg`。
  - macOS：`brew install ffmpeg`。

## 2. 安装与初始化

```bash
pip install -e ".[dev]"
narrascape version
narrascape init my-video
```

`init` 生成的项目包含 `config.yaml`、`scripts/script.yaml`、素材目录和管线状态目录。

## 3. 五分钟离线冒烟

把 `config.yaml` 改成全部 local provider：

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

然后：

```bash
narrascape build -p my-video --approve
```

这条链路会用占位图、蜂鸣音频和确定性导演逻辑跑完整条管线，产出真实拼接的视频文件。**离线模式只验证流程是通的，不产出影视级质量**——它存在的意义是让你在没有 API key、没有网络的情况下确认安装无误。

## 4. 第一个真实项目

### 4.1 配置 LLM：两种模式的取舍

**bridge 模式（`ai_assistant` / `bridge`）**：不需要 LLM API key。管线把 LLM 请求写成任务文件，由你的 AI 助手（如 Codex / Kimi）处理后回填响应。适合已有 AI 助手订阅、希望助手深度参与创作的人；代价是助手必须在环。

```yaml
llm:
  mode: ai_assistant
  timeout: 300
```

**api 模式**：直连 OpenAI 兼容 API，适合自动化和无人值守构建。

```yaml
llm:
  mode: api
  provider: openai
  model: gpt-4o
  api_key: "${OPENAI_API_KEY}"
```

要点：

- `config.yaml` 的字符串值支持 `${VAR}` 和 `${VAR:-default}` 环境变量插值，加载时展开——**不要把真实 key 贴进配置文件**。
- `mode: api` 下找不到 key 会直接报错退出，不会悄悄降级成 bridge 模式。key 的解析顺序是 `llm.api_key`，然后是对应 provider 的环境变量（`OPENAI_API_KEY`、`DEEPSEEK_API_KEY`、`ANTHROPIC_API_KEY`、`ARK_API_KEY`）。
- 明文写 `llm.api_key` 会在启动时告警。真实 key 请放在环境变量或 git 忽略的 `.env` 文件里。

### 4.2 配置媒体 provider 的 key

生产默认组合是 Seedream 生图 + Seedance 生视频 + MiniMax 配音配乐，对应两个环境变量：

```bash
export ARK_API_KEY=...       # Seedream 生图、Seedance 生视频（火山引擎）
export MINIMAX_API_KEY=...   # MiniMax TTS 配音、音乐
```

`images.provider`、`video.provider`、`tts.provider` 的默认值本身就是这套生产组合，一般不需要改。

### 4.3 构建

```bash
narrascape build -p my-video --approve
```

默认 `pipeline.video_generation: auto`：缺少 Seedance 凭证时会跳过 `generate_video`，用真实素材或生成图片兜底继续；要求每个镜头都必须生成视频时改成 `required`。最终产物在 `output/<project>-clean.mp4` 和 `output/<project>-sub.mp4`。

## 5. 人工审批工作流实战

Narrascape 的默认姿态是"每一步都要审核"。不加 `--approve` 运行：

```bash
narrascape build -p my-video
```

每完成一个阶段，管线就会停下并写入待审核标记。接下来：

```bash
narrascape status -p my-video                              # 看哪个阶段在等审核
narrascape approve -p my-video -s design                   # 检查产物后放行
narrascape reject -p my-video -s design --notes "重写人脸"  # 打回
narrascape build -p my-video                               # 再次运行，继续推进
```

打回重跑的行为是成本安全的：付费阶段（生图、生视频、TTS、音乐）只有在"输出文件存在**且**请求指纹匹配"时才复用产物——提示词、模型、参数、参考图内容任何一个变了指纹就变，才会重新生成。换句话说，改完设计重跑，只有受影响的付费请求会重新扣费。

另外两个审批相关模式：`--interactive` 每个阶段完成后在终端暂停当场审核；`--approve` 自动通过所有阶段，适合 CI。

## 6. 生产配置与预算

严格生产 profile：

```bash
narrascape build -p examples/golden-sample --production --approve
```

`--production` 应用 Seedream + Seedance + 油画风格、`video_generation: required`、严格导演模式、生产质量门、每镜头至少 3 个 take、最多 2 轮自动返工。

预算控制建议在 `config.yaml` 里显式设置：

```yaml
budget:
  total_usd: 10.0
  mode: warn        # observe | warn | cap
```

先用 `warn` 观察几个项目的实际花费，确认量级后再切 `cap` 硬封顶。付费失败（TTS 业务错误、视频任务失败/过期）也会记账，网络层错误记为零成本条目。

## 7. 常见问题

**YAML 里的 `off` 要不要加引号？**
不需要。`pipeline.video_generation: off` 裸写即可，配置加载时会自动归一（早期版本受 YAML 1.1 影响要求写 `"off"`，现已修复）。

**审批卡住了怎么办？**
先 `narrascape status -p my-video` 看卡在哪个阶段：pending 就 `approve` 放行或 `reject` 打回；rejected 状态下管线会停在该阶段，直到你修改后重新 approve。想一次性放行用 `--approve`，想强制重跑某阶段用 `--force`。

**成本在哪看？**
`pipeline/<project>/cost_report.yaml` 是汇总视图（`assistant_handoff` 阶段每次运行都会刷新它）；`pipeline/<project>/budget_state.json` 是逐笔台账，包含每条付费记录的状态与金额。

**崩溃后重跑会怎样？**
视频生成有 `video_tasks.json` 任务台账：任务创建时就落账，崩溃后重跑会继续轮询未完成的任务、从已成功的记录直接重新下载，而不会重复创建付费任务。其他付费阶段由请求指纹缓存保护，同样不会重复扣费。

**生成视频没被采用？**
`film_timeline` 的视觉优先级是生成视频 → 真实素材 → 生成图片兜底。多 take 场景下先跑 `take_select` 选出 take；如果存在 `vid_*_take_*.mp4` 但缺少 `take_selection.yaml`，`film_timeline` 会给出警告并只认基础 `vid_NN.mp4` 文件。

## 下一步

- [完整功能地图（英文）](features.md)
- [配置参考（英文）](config-reference.md)
- [AI 导演边界（英文）](ai-director.md)
- [各阶段文档索引](index.md#agent-stage-docs)
