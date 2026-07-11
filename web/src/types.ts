export type JobStatus =
  | "queued"
  | "running"
  | "cancelling"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface JobRecord {
  id: string;
  stage: string;
  status: JobStatus;
  command: string[];
  created_at: string;
  updated_at: string;
  log_path: string;
  return_code: number | null;
  resumed_from: string | null;
  error: string | null;
}

export interface Artifact {
  id: string;
  label: string;
  relative_path: string;
  path: string;
  exists: boolean;
  status: string;
  size_bytes: number;
  kind: string;
}

export interface StageNodeData extends Record<string, unknown> {
  id: string;
  stage: string;
  label: string;
  label_zh?: string;
  lane: string;
  kind: string;
  state: string;
  status: string;
  stage_status: string;
  approval: string;
  current: boolean;
  queued: boolean;
  exists: boolean;
  output_count: number;
  output_size: number;
  production_boundary: boolean;
  artifacts: Artifact[];
  output_files: Array<{ path: string; exists: boolean; size_bytes: number }>;
  intent: string;
  x: number;
  y: number;
}

export interface InspectorData extends StageNodeData {
  blocking_reason: string;
  depends_on: string[];
  outputs: string[];
  upstream: string[];
  downstream: string[];
  upstream_ids: string[];
  downstream_ids: string[];
  stage_doc: string;
}

export interface TimelineClip {
  id: string;
  segment_id?: number;
  source: string;
  path: string;
  start: number;
  duration: number;
  asset_exists: boolean;
  emotion?: string;
  shot_type?: string;
}

export interface Snapshot {
  project: {
    name: string;
    title: string;
    directory: string;
    pipeline_directory: string;
  };
  stages: Array<Record<string, unknown> & { name: string; label_zh: string; status: string }>;
  workbench: {
    stage_summary: {
      total: number;
      completed: number;
      progress: number;
      counts: Record<string, number>;
      current_stage?: { name: string } | null;
    };
    canvas: {
      nodes: StageNodeData[];
      edges: Array<{ from: string; to: string; state: string; label?: string }>;
      focus?: StageNodeData | null;
      summary: Record<string, number>;
    };
    node_inspector: Record<string, InspectorData>;
    artifacts: Artifact[];
    agent_queue: Array<Record<string, unknown>>;
    rework_loop: Record<string, unknown>;
    quality_gates: Array<Record<string, unknown>>;
    rework_queues: Array<Record<string, unknown>>;
  };
  timeline: {
    status: string;
    duration: number;
    visual: TimelineClip[];
    source_counts: Record<string, number>;
    missing_assets: Array<Record<string, unknown>>;
  };
  jobs: JobRecord[];
  active_job: JobRecord | null;
}
