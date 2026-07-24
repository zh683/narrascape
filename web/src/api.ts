import type { JobRecord, Snapshot } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `请求失败 (${response.status})`);
  }
  return (await response.json()) as T;
}

export const api = {
  snapshot: (signal?: AbortSignal) => request<Snapshot>("/api/snapshot", { signal }),
  runStage: (stage: string, options: { force: boolean; dry_run: boolean; approve: boolean }) =>
    request<JobRecord>(`/api/stages/${encodeURIComponent(stage)}/run`, {
      method: "POST",
      body: JSON.stringify(options),
    }),
  reviewStage: (stage: string, action: "approve" | "reject" | "skip", notes = "") =>
    request<{ stage: string; status: string }>(
      `/api/stages/${encodeURIComponent(stage)}/review`,
      { method: "POST", body: JSON.stringify({ action, notes, reviewer: "workbench" }) },
    ),
  cancelJob: (id: string) =>
    request<JobRecord>(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  resumeJob: (id: string) =>
    request<JobRecord>(`/api/jobs/${encodeURIComponent(id)}/resume`, { method: "POST" }),
  jobLog: (id: string) =>
    request<{ job_id: string; log: string }>(`/api/jobs/${encodeURIComponent(id)}/log?tail=800`),
};

export function mediaUrl(path: string): string {
  const normalized = path.replaceAll("\\", "/").replace(/^\.\//, "");
  return `/api/media/${normalized.split("/").map(encodeURIComponent).join("/")}`;
}
