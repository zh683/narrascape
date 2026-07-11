import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Clapperboard, Film, GitBranch, Menu, RefreshCw, RotateCcw, Settings2, SlidersHorizontal } from "lucide-react";
import { api } from "./api";
import { Inspector } from "./components/Inspector";
import { JobDock } from "./components/JobDock";
import { TimelineView } from "./components/TimelineView";
import { WorkflowCanvas } from "./components/WorkflowCanvas";
import { zhStatus } from "./labels";
import type { Snapshot, TimelineClip } from "./types";

type View = "workflow" | "timeline" | "rework";

export default function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedClip, setSelectedClip] = useState<TimelineClip | null>(null);
  const [view, setView] = useState<View>("workflow");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [dockOpen, setDockOpen] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [jobLog, setJobLog] = useState("");
  const [mobileNav, setMobileNav] = useState(false);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setRefreshing(true);
    try {
      const next = await api.snapshot(signal);
      setSnapshot(next);
      setSelectedId((current) => current ?? next.workbench.canvas.focus?.id ?? next.workbench.canvas.nodes[0]?.id ?? null);
      setError("");
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(reason instanceof Error ? reason.message : "无法读取项目状态");
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [refresh]);

  useEffect(() => {
    if (!selectedJobId) return;
    void api.jobLog(selectedJobId).then((result) => setJobLog(result.log)).catch((reason: Error) => setError(reason.message));
  }, [selectedJobId, snapshot?.jobs]);

  const inspector = selectedId && snapshot ? snapshot.workbench.node_inspector[selectedId] ?? null : null;
  const stageLabel = useMemo(() => snapshot?.stages.find((stage) => stage.name === inspector?.stage)?.label_zh ?? inspector?.label ?? "阶段", [inspector, snapshot]);
  const stageLabels = useMemo(
    () => Object.fromEntries((snapshot?.stages ?? []).map((stage) => [stage.name, stage.label_zh])),
    [snapshot?.stages],
  );

  const perform = useCallback(async (action: () => Promise<unknown>) => {
    setBusy(true);
    try { await action(); await refresh(); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败"); }
    finally { setBusy(false); }
  }, [refresh]);

  const runStage = (stage: string, force: boolean) => {
    const boundary = snapshot?.workbench.node_inspector[stage]?.production_boundary;
    if (boundary && !window.confirm(`即将按批次运行供应商阶段“${stageLabel}”。请确认当前供应商、模型和预算配置。`)) return;
    void perform(() => api.runStage(stage, { force, dry_run: false, approve: true }));
    setDockOpen(true);
  };

  if (!snapshot) {
    return <main className="boot-screen"><Clapperboard size={28} /><h1>Narrascape 制作工作台</h1><p>{error || "正在读取项目…"}</p></main>;
  }

  const progress = snapshot.workbench.stage_summary.progress;
  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="mobile-menu" title="打开导航" onClick={() => setMobileNav((value) => !value)}><Menu size={18} /></button>
        <div className="brand-mark"><Clapperboard size={18} /><strong>NARRASCAPE</strong></div>
        <div className="project-identity"><b>{snapshot.project.title}</b><span>{snapshot.project.name}</span></div>
        <div className="project-progress"><span><i style={{ width: `${progress}%` }} /></span><b>{progress}%</b></div>
        <button className="icon-button" title="刷新项目" onClick={() => void refresh()}><RefreshCw size={16} className={refreshing ? "spin" : ""} /></button>
        <button className="icon-button" title="工作台设置"><Settings2 size={16} /></button>
      </header>
      <nav className={`sidebar ${mobileNav ? "is-open" : ""}`}>
        <NavButton active={view === "workflow"} icon={<GitBranch />} label="制作流程" onClick={() => { setView("workflow"); setMobileNav(false); }} />
        <NavButton active={view === "timeline"} icon={<Film />} label="时间线" onClick={() => { setView("timeline"); setSelectedId("film_timeline"); setMobileNav(false); }} />
        <NavButton active={view === "rework"} icon={<RotateCcw />} label="返工队列" onClick={() => { setView("rework"); setMobileNav(false); }} />
        <div className="sidebar-spacer" />
        <NavButton active={false} icon={<Activity />} label="系统诊断" onClick={() => window.open("http://127.0.0.1:8501", "_blank")} />
      </nav>
      <main className="workspace">
        <section className="workspace-main">
          <div className="view-toolbar">
            <div><span className="eyebrow">{view === "workflow" ? "制作控制" : view === "timeline" ? "剪辑时间线" : "返工控制"}</span><h1>{view === "workflow" ? "制作流程" : view === "timeline" ? "影片时间线" : "返工与监督"}</h1></div>
            <div className="summary-strip">
              <Metric value={`${snapshot.workbench.stage_summary.completed}/${snapshot.workbench.stage_summary.total}`} label="完成阶段" />
              <Metric value={String(snapshot.workbench.agent_queue.length)} label="待办" />
              <Metric value={String(snapshot.timeline.missing_assets.length)} label="缺失素材" alert={snapshot.timeline.missing_assets.length > 0} />
            </div>
            <button className="icon-button" title="筛选与显示"><SlidersHorizontal size={16} /></button>
          </div>
          {error ? <div className="error-banner">{error}<button onClick={() => setError("")}>关闭</button></div> : null}
          {view === "workflow" ? <WorkflowCanvas snapshot={snapshot} selectedId={selectedId} onSelect={setSelectedId} /> : null}
          {view === "timeline" ? <TimelineView snapshot={snapshot} selectedClip={selectedClip} onSelect={setSelectedClip} /> : null}
          {view === "rework" ? <ReworkView snapshot={snapshot} onSelectStage={(id) => { setSelectedId(id); setView("workflow"); }} /> : null}
        </section>
        <Inspector data={inspector} label={stageLabel} busy={busy} activeJob={snapshot.active_job} stageLabels={stageLabels} onRun={runStage} onReview={(stage, action) => void perform(() => api.reviewStage(stage, action))} />
      </main>
      <JobDock
        jobs={snapshot.jobs}
        activeJob={snapshot.active_job}
        log={jobLog}
        open={dockOpen}
        refreshing={refreshing}
        onToggle={() => setDockOpen((value) => !value)}
        onCancel={(id) => void perform(() => api.cancelJob(id))}
        onResume={(id) => void perform(() => api.resumeJob(id))}
        onSelect={(id) => { setSelectedJobId(id); setDockOpen(true); }}
      />
    </div>
  );
}

function NavButton({ active, icon, label, onClick }: { active: boolean; icon: React.ReactNode; label: string; onClick: () => void }) {
  return <button className={active ? "active" : ""} onClick={onClick} title={label}>{icon}<span>{label}</span></button>;
}

function Metric({ value, label, alert = false }: { value: string; label: string; alert?: boolean }) {
  return <div className={alert ? "metric alert" : "metric"}><b>{value}</b><span>{label}</span></div>;
}

function ReworkView({ snapshot, onSelectStage }: { snapshot: Snapshot; onSelectStage: (id: string) => void }) {
  const stages = snapshot.workbench.agent_queue;
  return <div className="rework-view">
    <div className="rework-summary"><h2>监督回路</h2><dl>{Object.entries(snapshot.workbench.rework_loop).filter(([, value]) => typeof value !== "object").slice(0, 8).map(([key, value]) => <div key={key}><dt>{reworkLabels[key] ?? key}</dt><dd>{typeof value === "boolean" ? (value ? "是" : "否") : zhStatus(String(value))}</dd></div>)}</dl></div>
    <div className="queue-table"><div className="queue-table__head"><span>阶段</span><span>来源</span><span>原因</span><span>状态</span></div>{stages.length ? stages.map((item, index) => {
      const stage = String(item.stage ?? "");
      const label = snapshot.stages.find((entry) => entry.name === stage)?.label_zh ?? stage;
      return <button key={`${stage}-${index}`} onClick={() => onSelectStage(stage)}><b>{label}</b><span>{String(item.source ?? "监督器")}</span><span>{String(item.reason ?? "等待处理")}</span><em>{zhStatus(String(item.status ?? "queued"))}</em></button>;
    }) : <div className="empty-queue">当前没有返工任务</div>}</div>
  </div>;
}

const reworkLabels: Record<string, string> = {
  status: "回路状态",
  rework_status: "返工计划",
  supervisor_status: "监督状态",
  execution_status: "执行状态",
  action_count: "返工动作",
  executed_count: "已执行",
  qa_error_count: "QA 错误",
  qa_warning_count: "QA 警告",
  blocking: "是否阻塞",
};
