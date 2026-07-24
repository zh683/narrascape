# Narrascape 代码深度解析与优化方向报告

> 生成时间：2026-07-22（UTC+8）  ·  分析基线：HEAD `8d1c124`（2026-07-01）
> 方法：三路并行代码审计（核心编排层 / 集成层 / 质量验证运行）+ Google Scholar 四方向文献检索（2023 年后）

---

## 修复状态追踪（2026-07-24 更新）

> 本报告原有内容保留为历史审计快照（基线 `8d1c124`）。下列问题已在后续 10 个提交中逐项修复并验证（pytest 327 → 519，ruff/black/mypy strict 全程全绿，golden-sample 端到端通过）。当前 HEAD：`e921662`。

### P0 — 全部清零 ✅

| # | 问题 | 状态 | 修复提交 |
|---|---|---|---|
| P0-1 | generate_images finally 崩溃 | ✅ 已修复 | `9831441` |
| P0-2 | 已付费 task_id 不落盘（task_map 死代码） | ✅ 已修复（VideoTaskLedger 创建即落盘） | `70bd7c5` |
| P0-3 | 轮询上限 300s 不可配置致任务成孤儿 | ✅ 已修复（`VideoConfig.max_poll_time` 默认 900s + 超时反孤儿） | `70bd7c5` |
| P0-4 | 非幂等 POST 盲目重试 | ✅ 已修复（重试白名单；幂等键为 provider 侧限制，见残留风险） | `9831441` |
| P0-5 | 4xx 永久错误被指数退避重试 | ✅ 已修复（`is_retryable_http_error`：仅 408/429/5xx 可重试） | `9831441` |

### P1 — 全部清零 ✅

| # | 问题 | 状态 | 修复提交 |
|---|---|---|---|
| P1-1 | completed+pending 阶段静默重跑 | ✅ 已修复（pending 即 halt 并提示 approve） | `70bd7c5` |
| P1-2 | 编排层零并行、生成阶段串行 | ✅ 已修复（`--stage-parallel` 同层并发 + TTS/video `max_concurrency` 流水化，opt-in） | `39fc4bc` `fb043b5` |
| P1-3 | BuildCache 死代码 + 路径语义错误 | ✅ 已修复（连根删除，由请求指纹缓存替代） | `f3fc5b8` |
| P1-4 | catalog design_report 路径错误 | ✅ 已修复 | `9831441` |
| P1-5 | mode=api 缺 key 静默降级 | ✅ 已修复（显式报错退出） | `c83ff8f` |
| P1-6 | `${VAR}` 假插值 | ✅ 已修复（load_config 真插值，api_key 未命中加载期报错） | `c83ff8f` |
| P1-7 | bridge 锁无 stale 回收 / 非法 JSON 即崩 | ✅ 已修复（复用 safe_io.file_lock，60s 自愈；半截响应容错等待 + 超时诊断字段） | `7a50f62` |
| P1-8 | Agnes 429 假 Retry-After | ✅ 已修复（`delay_hint` 真实睡眠） | `11445af` |
| P1-9 | 去重仅看输出文件是否存在 | ✅ 已修复（请求指纹：prompt+模型+参数+参考内容哈希） | `f3fc5b8` |
| P1-10 | 成本台账只记成功、LLM 游离在外 | ✅ 已修复（失败记账恰好一次 + LLM token 进预算 + 费率可配） | `6b476cb` |
| P1-11 | .env 向上两级游走 / 明文 key 无防护 | ✅ 已修复（cwd-only + mtime 缓存 + 明文告警 + gitignore 约定） | `c83ff8f` |
| P1-12 | 契约无强类型 | ✅ 已修复（三大核心契约 pydantic 化，写点 fail-fast） | `46457a8` |

> 状态更新（2026-07-24 二更）：P1 已 **12/12 全部清零**。当前 HEAD：`7a50f62`，pytest 527 passed。

### P2 — 部分解决

| 问题 | 状态 | 提交 |
|---|---|---|
| take_select 字节数评分 | ✅ 已修复（ffmpeg 四信号质量分：清晰度/亮度/时长保真/帧稳定性） | `e921662` |
| `--parallel` 参数名误导 | ✅ 已修复（help 修正 + 新增 `--stage-parallel`） | `39fc4bc` |
| compose.py 假成功 stub | ⏳ 开放（`compose.py:37` 仍 `return True`，属死代码待清理） | — |
| 文档失真（architecture/design 与实现不符） | ✅ 已修复（各轮同步更新） | 多个 |
| 令牌桶并发竞态（修复中发现的新问题） | ✅ 已修复 | `39fc4bc` |
| 返工阶段链双份拷贝已漂移 | ⏳ 开放 | — |
| clean 三处重复维护 | ⏳ 开放 | — |
| prompt_safety 静默重写无日志 | ⏳ 开放 | — |
| film_timeline 欠声明 take_select 依赖 | ⏳ 开放 | — |
| design_report 查找优先级不一致 | ⏳ 开放 | — |
| build 退出码含中间返工轮失败 | ⏳ 开放 | — |
| CLI 单阶段命令样板/不写 state | ⏳ 开放 | — |
| _THREAD_LOCKS 永久增长 | ⏳ 开放 | — |
| 依赖无上界/无 lock | ⏳ 开放 | — |
| 6 处 except Exception: pass | ⏳ 开放 | — |

### 第四梯队（学术驱动）— 已落地 1/4

| 方向 | 状态 | 提交 |
|---|---|---|
| take_select 真实质量信号（VBench 式感知评分前置版） | ✅ 已落地 | `e921662` |
| 分镜即生成条件（STAGE/DrawVideo 路径） | ⏳ 开放 | — |
| MCTS 选 take（AniMaker 路径） | ⏳ 开放 | — |
| QA 断言维度对照 Stable cinemetrics 扩充 | ⏳ 开放 | — |

---

## 一、这是个什么样的项目（代码层面）

### 1.1 一句话定位

Narrascape 不是一个"一键文生视频"工具，而是一条 **以文件契约为骨架、以 LLM 为创意大脑、以商用生成 API 为摄像机的 AI 影片生产流水线**。它把电影工业的制片流程（剧本 → 前期 → 导演 → 分镜 → 拍摄 → 剪辑 → 审片 → 返工）逐阶段映射为 36 个可独立运行、可审批、可重跑的 Python 阶段，每个阶段读写磁盘上的 YAML/JSON artifact，构成一张可检查、可干预的生产图。

### 1.2 核心架构（基于真实代码）

| 机制 | 实现 | 位置 |
|---|---|---|
| 阶段注册 | 36 个阶段类硬编码于 `ALL_STAGES` 列表 | `src/narrascape/pipeline.py:78-115` |
| 阶段协议 | `Stage` ABC：`name`/`depends_on` 类属性 + `can_run()`/`run()` | `src/narrascape/stages/base.py:49-88` |
| 依赖解析 | 传递闭包 + Kahn 拓扑排序，同层按注册顺序 tie-break | `pipeline.py:145-194` |
| 状态传递 | **纯文件 artifact**，阶段间无内存共享（`context.state` 恒为空 dict） | `pipeline.py:512` |
| 执行状态 | `pipeline/<name>/state.json`，文件锁 + 原子写 | `pipeline.py:202-265`、`utils/safe_io.py` |
| 审批门 | `approvals/{stage}.{pending,approved,rejected,skipped}` 标记文件；默认非交互模式每完成一个阶段即停 | `pipeline_approval.py:47-328`、`pipeline.py:680-686` |
| 返工闭环 | `_run_with_auto_rework`：读 `film_supervisor.yaml` 的 `next_stages` → `rework_execute` 隔离失败片段、重置受影响阶段 → force 重跑，最多 N 轮 | `pipeline.py:456-493`、`stages/rework_execute.py` |
| LLM 抽象 | 工厂分发：bridge（文件交换，供 AI assistant 接管）/ api（OpenAI 兼容、Anthropic、DeepSeek、Volcengine）/ none（确定性离线） | `cli.py:144-301`、`llm/client.py`、`llm/bridge.py:68-289` |
| 媒体提供商 | 注册表 + 静态打分 + JSON 熔断器（3 连败熔断 300s）；**但真正的 HTTP 客户端全部内嵌在 stages/generate_*.py** | `providers/registry.py`、`stages/generate_video.py:623-1181` 等 |
| 安全 I/O | 原子写、跨进程文件锁（含 stale 清理）、下载魔数/Content-Type 双重校验、磁盘预检 | `utils/safe_io.py:36-278` |

### 1.3 设计哲学（从代码反推）

1. **创意与执行分层**：Prompt 模板（`prompt_compiler.py`）→ LLM 创意输出（导演判断、选 take、语义 QA）→ 离线确定性 fallback（仅测试用）。生产构建通过 `strict_director` / `production_quality_gates` 禁止 fallback。
2. **契约即文件**：`director_contract.yaml`（每镜头故事意图、连续性锁、prompt 蓝图、QA 断言）和 `film_timeline.yaml`（剪辑脊柱）是可执行契约，不是文档。
3. **视觉优先级链**：生成视频 → 素材库 footage → 生成图兜底（Ken Burns），`film_timeline` 阶段裁决。
4. **AI assistant 即一等公民**：bridge 模式把 LLM 调用变成"写任务文件、等响应文件"的进程间协议，`assistant_handoff` 阶段专门为 Codex 类助手生成接管包——这个项目本身被设计成可以由 AI 代理接力驾驶。

### 1.4 工程质量基线（实际运行结果）

| 验证项 | 结果 |
|---|---|
| `ruff check src tests` | ✅ 0 错误（9 族规则，15 条显式豁免） |
| `black --check src tests` | ✅ 120 文件无需改动 |
| `mypy`（strict + pydantic 插件） | ✅ 90 文件零问题 |
| `pytest` | ✅ **327 passed in 26.4s**，0 跳过 0 xfail |
| 行覆盖率（分支覆盖开启） | **61%**（84 源文件） |
| 危险模式 | 裸 `except:` 0 处、`eval/exec/pickle` 0 处、`shell=True` 0 处、HTTP 全部带 timeout、TODO/FIXME 0 处 |

覆盖洼地：`agent/cinematography_knowledge.py` 0%、`dashboard.py` 0%、`stages/concat.py` 15%、`stages/kenburns.py` 19%、`cli.py` 25%、`stages/generate_images.py` 37%——**渲染末端与 CLI 层基本无测试保护**。

**结论：这是一个工程纪律远超同类开源项目的早期原型（strict mypy + 全绿 CI 很少见），架构理念（文件契约 + 阶段图 + AI 接管协议）在学术上也站得住。但它的可靠性缺口集中在"钱"上——付费生成的失败处理，恰好是测试最少的地方。**

---

## 二、问题清单（按严重度）

### P0 — 阻断性 bug / 直接资金损失

| # | 位置 | 问题 | 影响 |
|---|---|---|---|
| P0-1 | `stages/generate_images.py:472-476` | `_generate_one` 的 `finally` 块无条件 `out_png.stat()`；失败路径下文件已被删除，`stat()` 抛 FileNotFoundError 覆盖 `return False` | 单张图失败 → 整个 generate_images 阶段崩溃，日志误导 |
| P0-2 | `stages/generate_video.py:247-248` | `task_map` 自称"持久化任务 ID 映射用于断点续传"，但**全仓库零写入**（死代码）。已付费 Seedance task_id 不落盘 | 进程崩溃/超时后已付费任务成孤儿，重跑创建**新付费任务**，同镜头重复扣费 |
| P0-3 | `stages/generate_video.py:101` | `max_poll_time` 默认仅 **300s** 且 config.yaml 无对应配置项 | 720p 视频生成常超 5 分钟；超时叠加 P0-2 = 付费结果丢失 + 重复扣费 |
| P0-4 | `generate_video.py:731-736`、`generate_images.py:481-497` 等 | 对**非幂等的创建类 POST** 在网络错误时盲目重试，无 idempotency key | 服务器已接单但响应丢失时，重试产生重复付费生成 |
| P0-5 | `generate_video.py:735`、`generate_tts.py:191` 等 | `retryable_exceptions` 含**全部 HTTPError**——4xx（401/403/422）永久性错误也指数退避重试 3-4 次 | 鉴权失败时每镜头白等数十秒；Agnes 路径每次 65-75s × 4 无效等待 |

### P1 — 重要设计缺陷

| # | 位置 | 问题 | 影响 |
|---|---|---|---|
| P1-1 | `pipeline.py:537-573` | 增量跳过要求 approval ∈ {approved, skipped}；**completed 但 pending 的阶段会被静默重跑** | 用户在审批前重复 `build` 会对已完成的 LLM/付费阶段重复扣费，违背审批门语义 |
| P1-2 | `pipeline.py:519-696`、`generate_*.py` | **编排层零并行**：36 阶段严格串行；生成阶段内部也串行（Seedream 每张 sleep 1.5s、Seedance 逐 take submit+poll）；CLI `--parallel N` 只对 kenburns 生效 | 长片耗时随段数线性放大；`--parallel` 参数名误导 |
| P1-3 | `cache.py:25-157` + 全仓库 | `BuildCache` 实例化后**零调用**（死代码），且 `is_cached` 路径解析本身就是错的 | 文档宣称的内容寻址缓存不存在；改上游 artifact 不触发下游重建 |
| P1-4 | `catalog.py:8` vs `design.py:257` | `design_report` 模板指向项目根，实际写在 `pipeline/<name>/` | `assistant_handoff.yaml` 永远报 design_report "missing"，**正在误导接管的 AI 助手** |
| P1-5 | `cli.py:196-211` | `mode=api` 但无 key 时**静默降级**到后续分支，不报错 | 生产构建可能悄悄退化为 bridge 占位，违反项目自身治理规则 |
| P1-6 | `docs/quickstart.md:62` vs `config.py:706-716` | 文档教用户写 `api_key: "${OPENAI_API_KEY}"`，但 `load_config` 无环境变量插值 | 字面量 `${OPENAI_API_KEY}` 被当 Bearer token 发出，鉴权失败且极难排查 |
| P1-7 | `llm/bridge.py:36-57, 205-210` | bridge 锁无 stale 回收；读到非法响应 JSON 立即抛错而非继续等待 | 持锁进程崩溃 → 永久卡死需人工删锁；外部助手非原子写响应 → 竞态崩溃 |
| P1-8 | `generate_video.py:873-877` + `utils/retry.py:50-55` | Agnes 429 处理是**假的**：日志算出 Retry-After 延迟，但回调无法改变实际睡眠时长 | 限流未被真正遵守，日志撒谎 |
| P1-9 | `generate_video.py:1134` 等 | 付费生成"去重"仅看输出文件是否存在，不看 prompt/参数/模型 | 改 prompt 不改文件名 → 静默复用过期素材；换文件名 → 全部重新付费 |
| P1-10 | `generate_tts.py:211-214`、`utils/budget.py` | 成本台账只记成功调用且按固定估计；LLM token 用量从不进 BudgetTracker | 预算 cap 与实际账单系统性偏离，给出虚假安全感 |
| P1-11 | `api_keys.py:13-32` | `.env` 从 cwd 向上找两级、无权限检查；`config.yaml` 明文 `api_key` 字段未被 gitignore 防护 | 密钥混淆与误提交泄露风险 |
| P1-12 | `artifacts.py:31-136` | 阶段间契约无强类型：裸 dict + 只校验顶层必填键，读取侧靠数十处 `.get()`/`isinstance` 防御 | schema 漂移无法及时发现；与 design.md "Pydantic models first" 的宣称不符 |

### P2 — 改进项（节选，完整见各分项审计）

- `film_supervisor.py:77-124` 与 `rework_execute.py:161-204` 的返工阶段链是两份拷贝，**已发生漂移**（前者含 `assistant_handoff`，后者不含）
- `take_select.py:122-127` 确定性评分 = **文件字节数**，与画质无关 —— **已修复**：确定性评分升级为 ffmpeg 抽帧质量信号组合（sharpness/brightness/duration/stability，见 `utils/video_quality.py` 与 `docs/agent-stages/take_select.md`），失败时按段回退字节数并 warning
- `compose.py:30-37` `FFmpegCompositionRuntime.render()` 直接 `return True` 假装成功
- `prompt_safety.py:7-66` 静默重写 prompt（blood→dark mark 等），无日志不入产物，导演层无法感知
- `film_timeline.py:42-44` 读 `take_selection.yaml` 但不声明 `take_select` 依赖，正确性依赖注册顺序的隐式约定
- `design_report` 查找优先级在不同阶段不一致（reference_plate 先查 pipeline_dir，其余先查 project_dir）
- build 退出码把所有返工 cycle 结果取 and：中间轮失败但后续修复成功，退出码仍为 1（CI 误报）
- `cli.py:461-955` 五个单阶段命令重复 30 行样板且绕开 Pipeline 不写 state.json，`narrascape status` 看不到
- `safe_io.py:22-33` `_THREAD_LOCKS` 字典永久增长；崩溃残留锁需等 600s
- 依赖全部 `>=` 无上界、无 lock 文件，CI 可复现性弱
- 6 处 `except Exception: pass` 静默吞错，其中 2 处在 `stages/qa.py`（QA 吞错最危险）

**正面确认（排查无问题）**：FFmpeg 参数有防注入封装；artifact 写入全原子化 + 文件锁；密钥未进日志/产物；无路径穿越入口；cap 模式预算扣减经文件锁原子完成。

---

## 三、学术文献映射（2023 年后）

四方向 Scholar 检索（CSV 已存工作区：`research_*.csv`），关键发现与项目映射：

| 领域 | 关键文献发现 | 对 Narrascape 的启示 |
|---|---|---|
| 多镜头身份一致性 | **Memento**（Wei et al., 2026）把跨镜头一致性归结为"身份锚定"问题；**EM-Vid**（Vandersanden et al., 2026）用免训练的实体中心记忆表征驱动多镜头生成；**AnyID**（Wang et al., CVPR 2026）从任意参考图保持人物动态身份 | 项目的 `continuity locks` + `reference_plate` 思路方向正确，但目前只是**文本 prompt 级**锁定；可升级为参考图/身份嵌入级的显式条件注入（项目已有 reference image 通道，缺的是把 continuity bible 编译进生成条件） |
| 分镜锚定的可控生成 | **STAGE**（Zhang et al., CVPR 2026）分镜锚定的多镜头叙事生成；**DrawVideo**（Xu et al., 2026）从分镜关键帧草图直接控制姿态/构图/相机；**SmartDirector**（Zhang et al., 2026）关键帧即分镜 + 叙事节奏控制；**MultiShotMaster**（Wang et al., CVPR 2026）显式控制主体运动与相机位置 | 项目的 storyboard_sheet → animatic → generate_video 链与学界主流收敛；差距在于**分镜仅作参考图而非生成条件**。Seedance 支持 image-to-video，可把分镜帧直接作为首尾帧条件（文献已验证此路径有效） |
| LLM 多智能体影片生产 | **AniMaker**（Shi et al., 2025）四智能体分工 + MCTS 驱动的片段生成；**Camera Artist**（Hu et al., 2026）多智能体电影语言框架，保持角色身份与空间连续性；**Direct**（Li et al., 2026）分层多智能体规划 + 意图引导剪辑 | 项目的 director/supervisor/review 多阶段评审结构与多智能体范式同构；可借鉴 **MCTS 选 take**（比当前"字节数评分"和单次 LLM judge 更稳）和**分层规划**（supervisor 分层决策而非单层 next_stages） |
| AIGC 视频质量评估 | **VBench** 体系已成事实标准；**AIGVQA**（Wang et al., ICCVW 2025）多维统一评估框架；**Video Inspector**（Somers et al., CVPR 2026）agentic-RL 的人类对齐评估；**Artifact-Bench**（Tang et al., 2026）专门检测生成伪影 | 项目 QA 目前以 ffprobe 黑帧/时长检测 + LLM 语义评审为主；可接入 VBench 式**自动化感知质量维度**（运动平滑度、主体一致性、审美分）作为 take_select 的真实质量信号，替代字节数评分 |
| 专业视频生成评估分类 | **Stable cinemetrics**（Chatterjee et al., NeurIPS 2025）提出专业视频生成的结构化分类法与评估，含"正确角色说正确台词"等细粒度检验 | 项目的 `director_contract.yaml` QA 断言可对照该分类法扩充维度，形成可审计的评估清单 |

---

## 四、优化方向路线图

### 第一梯队：立即修（小时级投入，直接止损）

1. **修 P0-1**：`generate_images.py` finally 块中 `stat()` 前先判 `exists()`，或把成功日志移出 finally。
2. **修 P0-4/P0-5**：重试白名单制——仅网络错误/5xx/429 可重试，4xx 立即失败。
3. **修 P1-4**：catalog 的 `design_report` 模板改为 `pipeline/<name>` 下路径——这个 bug 正在误导每一个接管的 AI 助手。
4. **修 P1-1**：completed+pending 阶段应 halt 等待审批，而非静默重跑。

### 第二梯队：付费可靠性（天级投入，工程层面收益最大）

5. **付费任务台账**（P0-2/P0-3）：task_map 做实——创建即持久化 `{task_id, provider, segment, prompt_hash, created_at}`，stage 启动先恢复轮询未完成 task；`max_poll_time` 进 config 并按分辨率/时长自适应。
6. **请求级内容寻址缓存**（P1-3/P1-9）：缓存键 = hash(prompt + model + size + 参考图内容)，接入 generate_* 各阶段；修活或删除 BuildCache，消除"改上游不重建下游"的盲区。
7. **统一 provider 客户端中间件**：把 stages/generate_*.py 里的 HTTP 代码收进 `providers/`（那三个空目录正等着），实现真正的 Retry-After、令牌桶限流、熔断联动。
8. **真实成本台账**（P1-10）：记录含失败在内的每次调用；LLM token 用量进 BudgetTracker；费率表按模型可配置。

### 第三梯队：架构升级（周级投入）

9. **DAG 并行调度**：`_run_once` 按拓扑层级并发同层阶段 + 生成阶段内 per-asset 信号量并发；review 层（continuity_bible/editing_review/creative_review 相互独立）天然可并行。文献侧 AniMaker/Camera Artist 均验证了并发智能体管线的可行性。
10. **契约 schema 化**：为 21 个 canonical artifact 定义 pydantic 模型（先覆盖 director_contract / film_timeline / film_supervisor），写出即校验，删掉读取侧大半防御代码——同时让 design.md 的宣称变为现实。
11. **artifact 寻址单一来源**：路径收敛进 catalog.py，clean/handoff/stage.outputs 全部派生，消除三处重复维护与查找优先级不一致。
12. **密钥管理收敛**（P1-5/P1-6/P1-11）：`load_config` 支持 `${VAR}` 插值、明文 key 告警、`mode=api` 缺 key 显式报错。

### 第四梯队：质量智能（学术驱动，与文献对标）

13. **take_select 真实质量信号**：接入 VBench 式感知维度（抽帧 + 主体一致性/运动/审美评分）替代字节数评分；中期可评估 MCTS 选 take（AniMaker 路径）。**进展**：字节数评分已由本地抽帧信号组合（清晰度/亮度/时长/冻结帧）替代；VBench 式语义/审美维度与 MCTS 仍待评估。
14. **分镜即生成条件**：把 storyboard 关键帧直接作为 Seedance image-to-video 的首帧条件（STAGE/DrawVideo/SmartDirector 已验证），而非仅作参考——这是把"storyboard-bound director contract"从治理概念变成物理约束的关键一步。
15. **QA 断言维度扩充**：对照 Stable cinemetrics 分类法扩充 director_contract 的 QA 断言；考虑接入 AIGVQA/Video Inspector 式自动评估作为 visual_semantic_qa 的确定性底座，LLM 评审只做高层语义。

---

## 五、参考文献

1. Wang J., Sheng H., Cai S., et al. 2026. AnyID: Ultra-Fidelity Universal Identity-Preserving Video Generation from Any Visual References. *CVPR 2026*.
2. Wei X., Ji L., Wang G., et al. 2026. Memento: Reconstruct to Remember for Consistent Long Video Generation. *arXiv:2606.14667*.
3. Vandersanden J., Gadelha M., Huang C.H.P., et al. 2026. EM-Vid: Training-Free Entity-Centric Memory for Efficient and Consistent Multi-Shot Video Generation. *arXiv:2605.23610*.
4. Zhang P., Jia Z., Liu K., et al. 2026. STAGE: Storyboard-Anchored Generation for Cinematic Multi-shot Narrative. *CVPR 2026*.
5. Xu C., Liang H., Shi B., et al. 2026. DrawVideo: Generating Long Video from Storyboard Keyframe Sketches. *arXiv:2605.23508*.
6. Zhang Z., Ma J., Peng Z., et al. 2026. SmartDirector: Keyframe-Conditioned Cinematic Video Generation with Narrative Pacing Control. *arXiv:2605.27891*.
7. Wang Q., Shi X., Li B., et al. 2026. MultiShotMaster: A Controllable Multi-Shot Video Generation Framework. *CVPR 2026*.
8. Wu X., Chen X., Wang Y., Qiao Y. 2026. ShotDirector: Directorially Controllable Multi-Shot Video Generation with Cinematographic Transitions. *CVPR 2026*.
9. Shi H., Li Y., Chen X., et al. 2025. AniMaker: Multi-Agent Animated Storytelling with MCTS-Driven Clip Generation. *ACM MM 2025*.
10. Hu H., Mao Q., Li Y., Jin L. 2026. Camera Artist: A Multi-Agent Framework for Cinematic Language Storytelling Video Generation. *arXiv:2604.09195*.
11. Li K., Li M., Chen J., et al. 2026. Direct: Video Mashup Creation via Hierarchical Multi-Agent Planning and Intent-Guided Editing. *arXiv:2604.04875*.
12. Liu X., Xiang X., Li Z., et al. 2024. A Survey of AI-Generated Video Evaluation. *arXiv:2410.19884*.
13. Wang J., Wang J., Zhu X., et al. 2025. AIGVQA: A Unified Framework for Multi-Dimensional Quality Assessment of AI-Generated Video. *ICCVW 2025*.
14. Somers J., Zale H., Mason J., et al. 2026. Video Inspector: An Agentic-RL Framework and Benchmark for Human-Aligned Generative Video Evaluation. *CVPR 2026 Findings*.
15. Tang Y., Shi Y., Zhang Z., et al. 2026. Artifact-Bench: Evaluating MLLMs on Detecting and Assessing the Artifacts of AI-Generated Videos. *arXiv:2605.18984*.
16. Chatterjee A., Entezari R., et al. 2025. Stable Cinemetrics: Structured Taxonomy and Evaluation for Professional Video Generation. *NeurIPS 2025*.
17. Han M., Yang L., Chang X., et al. 2025. Shot2story: A New Benchmark for Comprehensive Understanding of Multi-shot Videos. *ICLR 2025*.

---

*本报告基于只读代码审计与 Scholar 检索，未修改任何源码。文献 CSV 原始数据见工作区 `research_consistent_character.csv`、`research_controllable_video.csv`、`research_llm_agents_film.csv`、`research_video_qa.csv`。*
