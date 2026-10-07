"use client";

import { useState } from "react";
import { api, evidenceUrl } from "@/lib/api";
import { dateTime, videoTime } from "@/lib/format";
import { usePoll } from "@/lib/usePoll";
import type { QueryScope } from "@/types";

/** Events the model judged not worth remembering, with its reason (collapsed by default). */
export default function IgnoredEvents({ scope, count }: { scope: QueryScope; count: number }) {
  const [open, setOpen] = useState(false);
  if (count === 0) return null;

  return (
    <section>
      <button onClick={() => setOpen(!open)} className="text-sm text-zinc-400 hover:text-white">
        {open ? "▾" : "▸"} Ignored events ({count})
      </button>
      {open && <IgnoredList scope={scope} />}
    </section>
  );
}

function IgnoredList({ scope }: { scope: QueryScope }) {
  const { data } = usePoll(() => api.ignored(scope), [scope.device_id, scope.job_id], 5000);
  if (!data) return <p className="mt-2 text-sm text-zinc-500">Loading…</p>;

  return (
    <div className="mt-2 flex flex-col gap-2">
      {data.map((o) => (
        <div key={o.id} className="flex gap-3 rounded-lg border border-zinc-800/70 p-2 opacity-80">
          <div className="flex shrink-0 gap-1">
            {o.evidence.map((e) => (
              // eslint-disable-next-line @next/next/no-img-element
              <img key={e.url} src={evidenceUrl(e.url)} alt={e.name} className="h-12 w-16 rounded object-cover" />
            ))}
          </div>
          <div className="min-w-0 text-xs">
            <span className="font-mono text-zinc-500">
              {o.video_offset_s != null ? videoTime(o.video_offset_s) : dateTime(o.timestamp)}
            </span>
            <p className="mt-0.5 text-zinc-400">{o.result?.summary ?? "Not meaningful"}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
