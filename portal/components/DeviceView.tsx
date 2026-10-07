"use client";

import { api } from "@/lib/api";
import { dateTime, timeAgo } from "@/lib/format";
import { usePoll } from "@/lib/usePoll";
import AskBox from "./AskBox";
import IgnoredEvents from "./IgnoredEvents";
import Timeline from "./Timeline";

export default function DeviceView({ id }: { id: string }) {
  const device = usePoll(() => api.device(id), [id]);
  const memories = usePoll(() => api.memories({ device_id: id }), [id], 3000);
  const d = device.data;

  if (device.error && !d) return <p className="text-sm text-rose-400">{device.error}</p>;

  return (
    <div className="flex flex-col gap-6">
      <header>
        <div className="flex items-center gap-3">
          <span className={`h-2.5 w-2.5 rounded-full ${d?.status === "online" ? "bg-emerald-400" : "bg-zinc-600"}`} />
          <h1 className="text-xl font-semibold">{d?.name ?? id}</h1>
          <span className="text-sm text-zinc-500">{d?.status}</span>
        </div>
        {d && (
          <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-zinc-400">
            <span>ID {d.id}</span>
            <span>Last seen {timeAgo(d.last_seen)}</span>
            <span>Registered {dateTime(d.created_at)}</span>
            <span>
              {d.observation_count} events → {d.memory_count} memories
              {d.dismissed_count > 0 && ` · ${d.dismissed_count} ignored`}
              {d.pending_count > 0 && ` · ${d.pending_count} being analysed`}
              {d.failed_count > 0 && ` · ${d.failed_count} failed`}
            </span>
            {d.stats && (
              <span title="device-side filtering: sampled frames vs events sent">
                device: {d.stats.samples} frames sampled, {d.stats.discarded} blips dropped locally
                {d.stats.rss_mb ? ` · ${d.stats.rss_mb} MB RAM` : ""}
              </span>
            )}
          </div>
        )}
      </header>

      <AskBox scope={{ device_id: id }} label="this device" />

      <section>
        <h2 className="mb-3 text-sm font-medium text-zinc-300">Memory history</h2>
        <Timeline memories={memories.data} empty="No memories from this device yet." />
      </section>

      <IgnoredEvents scope={{ device_id: id }} count={d?.dismissed_count ?? 0} />
    </div>
  );
}
