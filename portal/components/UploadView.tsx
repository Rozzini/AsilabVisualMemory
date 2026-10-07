"use client";

import { api } from "@/lib/api";
import { dateTime, videoTime } from "@/lib/format";
import { usePoll } from "@/lib/usePoll";
import AskBox from "./AskBox";
import IgnoredEvents from "./IgnoredEvents";
import JobStatusBadge from "./JobStatusBadge";
import ProgressBar from "./ProgressBar";
import Timeline from "./Timeline";

export default function UploadView({ id }: { id: string }) {
  const job = usePoll(() => api.job(id), [id], 1500);
  const memories = usePoll(() => api.memories({ job_id: id }), [id], 2000);
  const j = job.data;

  if (job.error && !j) return <p className="text-sm text-rose-400">{job.error}</p>;

  const running = j && (j.status === "queued" || j.status === "processing" || j.status === "analyzing");

  return (
    <div className="flex flex-col gap-6">
      <header>
        <div className="flex items-center gap-3">
          <span className="text-zinc-500">▶</span>
          <h1 className="truncate text-xl font-semibold">{j?.filename ?? "Upload"}</h1>
          {j && <JobStatusBadge job={j} />}
        </div>
        {j && (
          <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-zinc-400">
            <span>Uploaded {dateTime(j.created_at)}</span>
            {j.duration_s != null && <span>Duration {videoTime(j.duration_s)}</span>}
            <span>
              {j.observations_total} events → {j.memory_count} memories
              {j.dismissed_count > 0 && ` · ${j.dismissed_count} ignored`}
            </span>
            {j.stats && <span>{j.stats.samples} frames sampled, {j.stats.discarded} discarded by change detector</span>}
          </div>
        )}
        {running && (
          <div className="mt-3 max-w-md">
            <ProgressBar
              progress={
                j.status === "processing"
                  ? j.progress
                  : j.status === "analyzing" && j.observations_total
                    ? j.observations_done / j.observations_total
                    : 0
              }
            />
            <p className="mt-1 text-xs text-zinc-500">
              {j.status === "queued" && "Waiting to be processed…"}
              {j.status === "processing" && "Sampling frames and detecting changes…"}
              {j.status === "analyzing" && "Qwen3-VL is interpreting the detected events…"}
            </p>
          </div>
        )}
        {j?.status === "failed" && <p className="mt-2 text-sm text-rose-400">{j.error}</p>}
      </header>

      <AskBox scope={{ job_id: id }} label="this video" />

      <section>
        <h2 className="mb-3 text-sm font-medium text-zinc-300">Memory history</h2>
        <Timeline
          memories={memories.data}
          empty={running ? "Memories will appear here as events are analysed…" : "No memories were created from this video."}
        />
      </section>

      {j && <IgnoredEvents scope={{ job_id: id }} count={j.dismissed_count} />}
    </div>
  );
}
