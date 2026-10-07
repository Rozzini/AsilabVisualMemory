import type { Job } from "@/types";

const STYLES: Record<Job["status"], string> = {
  queued: "bg-zinc-500/15 text-zinc-300",
  processing: "bg-indigo-500/15 text-indigo-300",
  analyzing: "bg-amber-500/15 text-amber-300",
  completed: "bg-emerald-500/15 text-emerald-300",
  failed: "bg-rose-500/15 text-rose-300",
};

export function jobStatusText(job: Job): string {
  switch (job.status) {
    case "processing":
      return `processing ${Math.round(job.progress * 100)}%`;
    case "analyzing":
      return `analyzing ${job.observations_done}/${job.observations_total}`;
    default:
      return job.status;
  }
}

export default function JobStatusBadge({ job, compact = false }: { job: Job; compact?: boolean }) {
  return (
    <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${STYLES[job.status]}`}>
      {compact ? job.status : jobStatusText(job)}
    </span>
  );
}
