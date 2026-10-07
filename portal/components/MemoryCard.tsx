"use client";

import Link from "next/link";
import { evidenceUrl } from "@/lib/api";
import { dateTime, EVENT_STYLES, eventLabel, videoTime } from "@/lib/format";
import type { Memory } from "@/types";

interface Props {
  memory: Memory;
  showSource?: boolean;
  highlight?: boolean;
  onOpen: (m: Memory) => void;
}

export default function MemoryCard({ memory: m, showSource = false, highlight = false, onOpen }: Props) {
  const thumbs = m.evidence.filter((e) => e.name !== "mid");
  const when = m.source === "upload" && m.video_offset_s != null ? videoTime(m.video_offset_s) : dateTime(m.timestamp);

  return (
    <article
      className={`flex gap-4 rounded-lg border p-3 ${
        highlight ? "border-indigo-500/60 bg-indigo-500/5" : "border-zinc-800 bg-zinc-900/60"
      }`}
    >
      <button onClick={() => onOpen(m)} className="flex shrink-0 gap-1" title="View evidence">
        {thumbs.map((e) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={e.url}
            src={evidenceUrl(e.url)}
            alt={e.name}
            className="h-20 w-28 rounded border border-zinc-800 object-cover hover:border-zinc-500"
          />
        ))}
      </button>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="font-mono text-zinc-400">{when}</span>
          <span className={`rounded px-1.5 py-0.5 ring-1 ${EVENT_STYLES[m.event_type] ?? EVENT_STYLES.other}`}>
            {eventLabel(m.event_type)}
          </span>
          {m.confidence != null && <span className="text-zinc-500">{Math.round(m.confidence * 100)}%</span>}
          {showSource &&
            (m.source === "device" ? (
              <Link href={`/devices/${encodeURIComponent(m.device_id ?? "")}`} className="text-zinc-400 hover:text-white">
                ◉ {m.device_name ?? m.device_id}
              </Link>
            ) : (
              <Link href={`/uploads/${m.job_id}`} className="text-zinc-400 hover:text-white">
                ▶ {m.job_filename}
              </Link>
            ))}
        </div>
        <p className="mt-1 text-sm text-zinc-100">{m.summary}</p>
        {m.objects.length > 0 && (
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {m.objects.map((o, i) => (
              <li key={i} className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-300">
                <span className="font-medium">{o.name}</span>
                {(o.location_before || o.location_after) && (
                  <span className="text-zinc-500">
                    {" "}
                    {o.location_before && o.location_after && o.location_before !== o.location_after
                      ? `${o.location_before} → ${o.location_after}`
                      : o.location_after ?? o.location_before}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </article>
  );
}
