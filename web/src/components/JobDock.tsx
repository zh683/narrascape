import { ChevronDown, ChevronUp, CircleStop, RefreshCw, RotateCcw, Terminal } from "lucide-react";
import { zhStatus } from "../labels";
import type { JobRecord } from "../types";

interface Props {
  jobs: JobRecord[];
  activeJob: JobRecord | null;
  log: string;
  open: boolean;
  onToggle: () => void;
  onCancel: (id: string) => void;
  onResume: (id: string) => void;
  onSelect: (id: string) => void;
  refreshing: boolean;
}

export function JobDock({ jobs, activeJob, log, open, onToggle, onCancel, onResume, onSelect, refreshing }: Props) {
  return (
    <section className={`job-dock ${open ? "is-open" : ""}`}>
      <button className="job-dock__bar" onClick={onToggle} aria-expanded={open}>
        <Terminal size={15} />
        <strong>作业控制台</strong>
        {activeJob ? <span className="active-job"><RefreshCw size={12} className={refreshing ? "spin" : ""} />{activeJob.stage} · {zhStatus(activeJob.status)}</span> : <span className="idle-job">当前无活动作业</span>}
        <span className="job-count">{jobs.length} 条记录</span>
        {open ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
      </button>
      {open ? (
        <div className="job-dock__content">
          <div className="job-list">
            {jobs.map((job) => (
              <button key={job.id} onClick={() => onSelect(job.id)}>
                <span className={`job-state job-${job.status}`} />
                <div><b>{job.stage}</b><small>{new Date(job.created_at).toLocaleString("zh-CN")}</small></div>
                <em>{zhStatus(job.status)}</em>
                {job.status === "running" || job.status === "queued" ? (
                  <span className="job-action" role="button" title="取消作业" onClick={(event) => { event.stopPropagation(); onCancel(job.id); }}><CircleStop size={15} /></span>
                ) : job.status === "failed" || job.status === "cancelled" || job.status === "interrupted" ? (
                  <span className="job-action" role="button" title="恢复作业" onClick={(event) => { event.stopPropagation(); onResume(job.id); }}><RotateCcw size={15} /></span>
                ) : null}
              </button>
            ))}
          </div>
          <pre className="job-log">{log || "选择作业查看日志"}</pre>
        </div>
      ) : null}
    </section>
  );
}
