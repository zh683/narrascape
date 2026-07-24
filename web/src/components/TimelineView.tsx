import { Film, Image, TriangleAlert } from "lucide-react";
import { mediaUrl } from "../api";
import { sourceLabels } from "../labels";
import type { Snapshot, TimelineClip } from "../types";

interface Props {
  snapshot: Snapshot;
  selectedClip: TimelineClip | null;
  onSelect: (clip: TimelineClip) => void;
}

export function TimelineView({ snapshot, selectedClip, onSelect }: Props) {
  const { timeline } = snapshot;
  const duration = Math.max(timeline.duration, 1);
  const ticks = Array.from({ length: Math.ceil(duration / 5) + 1 }, (_, index) => index * 5);
  return (
    <div className="timeline-view">
      <div className="timeline-ruler">
        {ticks.map((tick) => (
          <span key={tick} style={{ left: `${(tick / duration) * 100}%` }}>{formatTime(tick)}</span>
        ))}
      </div>
      <div className="timeline-track-row">
        <div className="track-label"><Film size={15} />画面</div>
        <div className="timeline-track">
          {timeline.visual.map((clip) => (
            <button
              className={`timeline-clip source-${clip.source} ${selectedClip?.id === clip.id ? "is-selected" : ""}`}
              key={clip.id}
              style={{ left: `${(clip.start / duration) * 100}%`, width: `${Math.max((clip.duration / duration) * 100, 2)}%` }}
              onClick={() => onSelect(clip)}
              title={`${clip.id} · ${clip.duration.toFixed(1)} 秒`}
            >
              <span>{clip.segment_id ?? "-"}</span>
              {!clip.asset_exists ? <TriangleAlert size={12} /> : null}
            </button>
          ))}
        </div>
      </div>
      <div className="timeline-track-row timeline-audio-row">
        <div className="track-label">声音</div>
        <div className="timeline-track audio-wave" aria-label="音频轨道" />
      </div>
      {selectedClip ? <ClipPreview clip={selectedClip} /> : (
        <div className="timeline-empty"><Image size={18} />选择片段查看真实素材</div>
      )}
    </div>
  );
}

function ClipPreview({ clip }: { clip: TimelineClip }) {
  const isVideo = /\.(mp4|mov|mkv|webm)$/i.test(clip.path);
  return (
    <div className="clip-preview">
      <div className="clip-preview__media">
        {clip.asset_exists && clip.path ? (
          isVideo ? <video src={mediaUrl(clip.path)} controls preload="metadata" /> : <img src={mediaUrl(clip.path)} alt={`片段 ${clip.id}`} />
        ) : <div className="missing-media"><TriangleAlert size={22} />素材不可用</div>}
      </div>
      <dl>
        <div><dt>片段</dt><dd>{clip.id}</dd></div>
        <div><dt>来源</dt><dd>{sourceLabels[clip.source] ?? clip.source}</dd></div>
        <div><dt>入点</dt><dd>{formatTime(clip.start)}</dd></div>
        <div><dt>时长</dt><dd>{clip.duration.toFixed(2)} 秒</dd></div>
        <div><dt>景别</dt><dd>{clip.shot_type ?? "未标注"}</dd></div>
        <div><dt>情绪</dt><dd>{clip.emotion ?? "未标注"}</dd></div>
      </dl>
    </div>
  );
}

function formatTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}
