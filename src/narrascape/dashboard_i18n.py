from __future__ import annotations

from typing import Any

STAGE_LABELS_ZH: dict[str, str] = {
    "research": "资料调研",
    "write": "脚本写作",
    "humanize": "口语润色",
    "source_media": "源素材",
    "footage_edit": "素材剪辑",
    "pre_production": "前期设定",
    "design": "镜头设计",
    "screenplay_structure": "剧作结构",
    "director_contract": "导演契约",
    "reference_plate": "参考图板",
    "generate_images": "生成图像",
    "storyboard_sheet": "分镜表",
    "animatic": "动态分镜",
    "production_readiness": "生成门检",
    "generate_video": "生成视频",
    "take_select": "多 Take 选择",
    "generate_tts": "旁白配音",
    "film_timeline": "影片时间线",
    "remotion_preview": "Remotion 预览",
    "film_assemble": "影片组装",
    "generate_music": "生成音乐",
    "remix_audio": "音频混音",
    "kenburns": "图片运动",
    "concat": "视频拼接",
    "audio": "成片音频",
    "subtitles": "字幕烧录",
    "qa": "渲染 QA",
    "continuity_bible": "连贯性圣经",
    "editing_review": "剪辑审查",
    "director_review": "导演审查",
    "rework_plan": "返工计划",
    "creative_review": "创意审查",
    "visual_semantic_qa": "视觉语义 QA",
    "film_supervisor": "影片监督",
    "assistant_handoff": "Agent 交接包",
    "rework_execute": "返工执行",
}

ARTIFACT_LABELS_ZH: dict[str, str] = {
    "script": "脚本",
    "pre_production": "前期设定",
    "design_report": "设计报告",
    "screenplay_structure": "剧作结构",
    "director_contract": "导演契约",
    "reference_plates": "参考图板",
    "storyboard_sheet": "分镜表",
    "animatic": "动态分镜",
    "production_readiness": "生产就绪门检",
    "video_prompt_quality": "视频提示质量",
    "take_selection": "多 Take 选择",
    "film_timeline": "影片时间线",
    "render_report": "渲染报告",
    "continuity_bible": "连贯性圣经",
    "editing_review": "剪辑审查",
    "director_review": "导演审查",
    "rework_plan": "返工计划",
    "creative_review": "创意审查",
    "visual_semantic_report": "视觉语义报告",
    "film_supervisor": "影片监督",
    "assistant_handoff": "Agent 交接包",
    "rework_execution": "返工执行",
    "director_contract_rewrite_queue": "导演契约重写队列",
    "video_regen_queue": "视频重生成队列",
    "recut_queue": "重剪队列",
    "source_media_replacement_queue": "源素材替换队列",
}

LANE_LABELS_ZH: dict[str, str] = {
    "Source": "源头",
    "Source Media": "源素材",
    "Pre-Production": "前期",
    "AI Director": "AI 导演",
    "Visual Contract": "视觉契约",
    "Reference Assets": "参考资产",
    "Storyboard": "分镜",
    "Generation Gate": "生成门检",
    "Generated Video": "生成视频",
    "Audio Source": "声音源",
    "Fallback Motion": "兜底运动",
    "Editorial": "剪辑",
    "Finishing": "后期",
    "QA": "质量检查",
    "Review": "审查",
    "Supervisor": "监督",
    "Handoff": "交接",
    "Rework": "返工",
    "Rework Queue": "返工队列",
    "Stage": "阶段",
    "Artifact": "产物",
}

STATUS_LABELS_ZH: dict[str, str] = {
    "active": "进行中",
    "approved": "已批准",
    "available": "可用",
    "awaiting_artifact": "等待产物",
    "blocked": "已阻塞",
    "completed": "已完成",
    "current": "当前",
    "done": "已完成",
    "empty": "空队列",
    "executed": "已执行",
    "failed": "失败",
    "fallback_after_error": "错误后兜底",
    "handoff_routed": "交接指派",
    "has_errors": "有错误",
    "idle": "空闲",
    "invalid": "格式异常",
    "missing": "缺失",
    "missing_assets": "素材缺失",
    "needs_attention": "需关注",
    "needs_rework": "需要返工",
    "not_configured": "未配置",
    "not_started": "未开始",
    "ok": "正常",
    "passed": "已通过",
    "pending": "待处理",
    "pending_supervisor": "等待监督",
    "present": "已存在",
    "queue_routed": "队列指派",
    "queued": "排队中",
    "ready": "就绪",
    "ready_for_handoff": "可交接",
    "rejected": "已拒绝",
    "running": "运行中",
    "stage_ready": "阶段就绪",
    "supervisor_routed": "监督指派",
    "unknown": "未知",
}

KIND_LABELS_ZH: dict[str, str] = {
    "agent": "Agent",
    "gate": "门检",
    "provider": "供应商",
    "qa": "审查",
    "queue": "队列",
    "stage": "阶段",
    "timeline": "时间线",
}

EDGE_LABELS_ZH: dict[str, str] = {
    "depends": "依赖",
    "feeds": "回流",
    "writes": "写入",
}

SOURCE_LABELS_ZH: dict[str, str] = {
    "current": "当前指针",
    "handoff": "交接包",
    "queue": "队列",
    "rework_queue": "返工队列",
    "status": "状态",
    "suggested": "建议",
    "supervisor": "影片监督",
    "generated_video": "生成视频",
    "source_media": "源素材",
    "source_footage": "源素材",
    "generated_image": "生成图像",
    "ending_card": "片尾卡",
    "unknown": "未分类",
}

LIFECYCLE_LABELS_ZH: dict[str, str] = {
    "takeover": "接管",
    "plan": "编排",
    "execute": "执行",
    "poll": "轮询",
    "handoff": "交接",
}

LIFECYCLE_DESCRIPTIONS_ZH: dict[str, str] = {
    "takeover": "读取流水线状态与交接包",
    "plan": "解析监督路线与阻塞产物",
    "execute": "运行已批准的 Narrascape 阶段",
    "poll": "刷新状态、交接包与生成产物",
    "handoff": "交出可继续接管的项目状态",
}

HANDLE_LABELS_ZH: dict[str, str] = {
    "Assistant Handoff": "Agent 交接包",
    "Pipeline Canvas": "项目画布",
    "Pipeline State": "流水线状态",
}

PROTOCOL_LABELS_ZH: dict[str, str] = {
    "qa_refresh": "QA 与交接刷新",
    "read_required": "读取必读上下文",
    "refresh_handoff": "刷新交接包",
    "run_next": "运行下一阶段",
    "status": "刷新状态",
}

QUALITY_GATE_LABELS_ZH: dict[str, str] = {
    "llm_mode": "LLM 模式",
    "production_quality_gates": "生产质量门",
    "production_readiness": "生产就绪",
    "qa_errors": "QA 错误",
    "strict_director": "严格导演模式",
    "video_generation": "视频生成要求",
}

REQUIRED_REASON_LABELS_ZH: dict[str, str] = {
    "AI Director boundaries and fallback rules": "AI 导演边界与兜底规则",
    "project positioning and production profile": "项目定位与生产配置",
    "standard AI assistant takeover flow": "标准 Agent 接管流程",
}


def zh_stage_label(stage_name: str, fallback: str | None = None) -> str:
    return STAGE_LABELS_ZH.get(stage_name, fallback or _humanize_id(stage_name))


def zh_artifact_label(artifact_id: str, fallback: str | None = None) -> str:
    return ARTIFACT_LABELS_ZH.get(artifact_id, fallback or _humanize_id(artifact_id))


def zh_lane_label(label: str) -> str:
    return LANE_LABELS_ZH.get(label, label)


def zh_status(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if value is None:
        return ""
    text = str(value)
    return STATUS_LABELS_ZH.get(text.lower(), text)


def zh_kind(value: str) -> str:
    return KIND_LABELS_ZH.get(value, value)


def zh_edge_label(value: str) -> str:
    return EDGE_LABELS_ZH.get(value, value)


def zh_source(value: str) -> str:
    return SOURCE_LABELS_ZH.get(value, value)


def zh_lifecycle_label(value: str) -> str:
    return LIFECYCLE_LABELS_ZH.get(value, value)


def zh_lifecycle_description(value: str, fallback: str) -> str:
    return LIFECYCLE_DESCRIPTIONS_ZH.get(value, fallback)


def zh_handle_label(value: str) -> str:
    return HANDLE_LABELS_ZH.get(value, value)


def zh_protocol_label(protocol_id: str, fallback: str) -> str:
    return PROTOCOL_LABELS_ZH.get(protocol_id, fallback)


def zh_quality_gate_label(value: str) -> str:
    return QUALITY_GATE_LABELS_ZH.get(value, value)


def zh_required_reason(value: str) -> str:
    return REQUIRED_REASON_LABELS_ZH.get(value, value)


def zh_reason(value: str) -> str:
    if not value:
        return ""
    if value == "film_supervisor requested this stage":
        return "影片监督请求继续该阶段"
    if value == "refresh the assistant takeover packet":
        return "刷新 Agent 交接包，确保下一次接管读取最新状态"
    if value == "all tracked workbench artifacts are present":
        return "已追踪的工作台产物均已存在"
    if value.startswith("stage is "):
        return f"阶段状态为 {zh_status(value.removeprefix('stage is '))}"
    if value.endswith(" is missing"):
        return f"缺少产物 {value.removesuffix(' is missing')}"
    if " queued action(s)" in value:
        return "返工队列中已有待执行动作"
    return value


def _humanize_id(value: str) -> str:
    return value.replace("_", " ").title() if value else ""
