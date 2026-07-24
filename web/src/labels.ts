const statusLabels: Record<string, string> = {
  pending: "待处理",
  running: "运行中",
  completed: "已完成",
  succeeded: "已成功",
  failed: "失败",
  queued: "已排队",
  cancelling: "取消中",
  cancelled: "已取消",
  interrupted: "已中断",
  approved: "已批准",
  rejected: "已拒绝",
  skipped: "已跳过",
  unknown: "未知",
  missing: "缺失",
  ready: "就绪",
  needs_rework: "需要返工",
};

export function zhStatus(value: string | null | undefined): string {
  if (!value) return "未知";
  return statusLabels[value.toLowerCase()] ?? value;
}

export const sourceLabels: Record<string, string> = {
  generated_video: "生成视频",
  source_footage: "源素材",
  generated_image: "生成图像",
  ending_card: "片尾",
  unknown: "未分类",
};
