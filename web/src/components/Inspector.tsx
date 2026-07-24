import { Check, CircleAlert, FileText, Play, RotateCcw, SkipForward, X } from "lucide-react";
import { zhStatus } from "../labels";
import type { InspectorData, JobRecord } from "../types";

interface Props {
  data: InspectorData | null;
  label: string;
  busy: boolean;
  activeJob: JobRecord | null;
  stageLabels: Record<string, string>;
  onRun: (stage: string, force: boolean) => void;
  onReview: (stage: string, action: "approve" | "reject" | "skip") => void;
}

export function Inspector({ data, label, busy, activeJob, stageLabels, onRun, onReview }: Props) {
  if (!data) return <aside className="inspector"><div className="empty-panel">选择一个制作阶段</div></aside>;
  const blocked = Boolean(activeJob) || busy;
  return (
    <aside className="inspector">
      <div className="inspector__heading">
        <div><span className="eyebrow">阶段检查器</span><h2>{label}</h2></div>
        <span className={`status-dot status-${data.stage_status}`}>{zhStatus(data.stage_status)}</span>
      </div>
      <p className="stage-intent">{localizedIntent(data.intent, label)}</p>
      {data.production_boundary ? (
        <div className="provider-boundary"><CircleAlert size={16} /><span>供应商执行边界</span><b>运行前核对模型与预算</b></div>
      ) : null}
      <div className="action-bar">
        <button className="button-primary" disabled={blocked} onClick={() => onRun(data.stage, false)}><Play size={15} fill="currentColor" />运行</button>
        <button className="icon-button" title="强制重建" disabled={blocked} onClick={() => onRun(data.stage, true)}><RotateCcw size={16} /></button>
        <button className="icon-button" title="批准阶段" onClick={() => onReview(data.stage, "approve")}><Check size={16} /></button>
        <button className="icon-button" title="拒绝阶段" onClick={() => onReview(data.stage, "reject")}><X size={16} /></button>
        <button className="icon-button" title="跳过阶段" onClick={() => onReview(data.stage, "skip")}><SkipForward size={16} /></button>
      </div>
      <Section title="执行状态">
        <DataRow label="流水线" value={zhStatus(data.stage_status)} />
        <DataRow label="审批" value={zhStatus(data.approval)} />
        <DataRow label="上游" value={data.upstream_ids.map((id) => stageLabels[id] ?? id).join(" / ") || "无"} />
        <DataRow label="下游" value={data.downstream_ids.map((id) => stageLabels[id] ?? id).join(" / ") || "无"} />
      </Section>
      <Section title={`产物 ${data.artifacts.length}`}>
        {data.artifacts.length ? data.artifacts.map((artifact) => (
          <div className="artifact-row" key={artifact.id}>
            <FileText size={14} />
            <div><b>{artifactLabels[artifact.id] ?? artifact.label}</b><span>{artifact.relative_path}</span></div>
            <i className={artifact.exists ? "exists" : "missing"}>{artifact.exists ? "就绪" : "缺失"}</i>
          </div>
        )) : <div className="muted-row">该阶段尚无登记产物</div>}
      </Section>
      {data.blocking_reason ? <Section title="当前约束"><p className="constraint">{localizedConstraint(data.blocking_reason)}</p></Section> : null}
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="inspector-section"><h3>{title}</h3>{children}</section>;
}

function DataRow({ label, value }: { label: string; value: string }) {
  return <div className="data-row"><span>{label}</span><b>{value}</b></div>;
}

function localizedIntent(intent: string, label: string): string {
  if (/[\u3400-\u9fff]/.test(intent)) return intent;
  return `${label}阶段负责读取上游契约并生成可审查、可恢复的标准流水线产物。`;
}

function localizedConstraint(reason: string): string {
  if (/[\u3400-\u9fff]/.test(reason)) return reason;
  if (reason === "Current pipeline cursor is here.") return "当前流水线指针位于此阶段。";
  if (reason.includes("Provider boundary")) return "供应商执行边界：运行前必须核对供应商、模型、目标阶段、原因以及样本或批次模式。";
  if (reason.includes("has not been written")) return "该阶段的核心产物尚未写入。";
  if (reason.includes("Approval gate")) return "该阶段仍受审批门禁约束。";
  if (reason.includes("failed")) return "该阶段上次执行失败，需要检查日志后重试。";
  return "该阶段正在等待上游产物、审批或监督器路由。";
}

const artifactLabels: Record<string, string> = {
  script: "脚本",
  pre_production: "前期设定",
  design_report: "设计报告",
  screenplay_structure: "剧作结构",
  director_contract: "导演契约",
  reference_plates: "参考图板",
  storyboard_sheet: "分镜表",
  animatic: "动态分镜",
  production_readiness: "生产就绪门检",
  video_prompt_quality: "视频提示质量",
  take_selection: "多 Take 选择",
  film_timeline: "影片时间线",
  render_report: "渲染报告",
  continuity_bible: "连贯性圣经",
  editing_review: "剪辑审查",
  director_review: "导演审查",
  rework_plan: "返工计划",
  creative_review: "创意审查",
  visual_semantic_report: "视觉语义报告",
  film_supervisor: "影片监督",
  assistant_handoff: "Agent 交接包",
  rework_execution: "返工执行",
};
