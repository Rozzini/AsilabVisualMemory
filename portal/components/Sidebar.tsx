"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";
import { timeAgo, dateTime } from "@/lib/format";
import { usePoll } from "@/lib/usePoll";
import UploadButton from "./UploadButton";
import JobStatusBadge from "./JobStatusBadge";
import ModelStatus from "./ModelStatus";
import ProgressBar from "./ProgressBar";

function NavItem({ href, active, children }: { href: string; active: boolean; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className={`block rounded-md px-3 py-2 text-sm transition ${
        active ? "bg-zinc-800 text-white" : "text-zinc-300 hover:bg-zinc-800/60"
      }`}
    >
      {children}
    </Link>
  );
}

export default function Sidebar() {
  const path = usePathname();
  const devices = usePoll(api.devices, []);
  const jobs = usePoll(api.jobs, []);
  const offline = devices.error && jobs.error;

  return (
    <aside className="flex w-72 shrink-0 flex-col gap-6 overflow-y-auto border-r border-zinc-800 bg-zinc-950 p-4">
      <Link href="/" className="flex items-center gap-2 px-1">
        <span className="text-xl">◉</span>
        <span className="font-semibold tracking-tight">Visual Memory</span>
      </Link>

      {offline ? (
        <p className="rounded-md bg-rose-500/10 p-2 text-xs text-rose-300">
          Cannot reach the API. Is the backend running?
        </p>
      ) : (
        <ModelStatus />
      )}

      <nav className="flex flex-col gap-1">
        <NavItem href="/" active={path === "/"}>
          All memories
        </NavItem>
      </nav>

      <section>
        <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wider text-zinc-500">Devices</h2>
        <div className="flex flex-col gap-1">
          {devices.data?.length === 0 && (
            <p className="px-1 text-xs text-zinc-500">
              No devices yet. Run <code className="text-zinc-300">visual-memory-agent --webcam</code>
            </p>
          )}
          {devices.data?.map((d) => (
            <NavItem key={d.id} href={`/devices/${encodeURIComponent(d.id)}`} active={path === `/devices/${encodeURIComponent(d.id)}`}>
              <div className="flex items-center gap-2">
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${d.status === "online" ? "bg-emerald-400" : "bg-zinc-600"}`}
                />
                <span className="truncate">{d.name}</span>
              </div>
              <div className="mt-0.5 pl-4 text-xs text-zinc-500">
                {d.status === "online" ? "online" : `seen ${timeAgo(d.last_seen)}`} · {d.memory_count} memories
              </div>
            </NavItem>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wider text-zinc-500">Uploaded videos</h2>
        <div className="mb-2">
          <UploadButton />
        </div>
        <div className="flex flex-col gap-1">
          {jobs.data?.length === 0 && <p className="px-1 text-xs text-zinc-500">No uploads yet.</p>}
          {jobs.data?.map((j) => (
            <NavItem key={j.id} href={`/uploads/${j.id}`} active={path === `/uploads/${j.id}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="truncate">{j.filename}</span>
                <JobStatusBadge job={j} compact />
              </div>
              <div className="mt-0.5 text-xs text-zinc-500">
                {dateTime(j.created_at)} · {j.memory_count} memories
              </div>
              {(j.status === "processing" || j.status === "analyzing") && (
                <ProgressBar progress={j.status === "processing" ? j.progress : analyzed(j)} />
              )}
            </NavItem>
          ))}
        </div>
      </section>
    </aside>
  );
}

function analyzed(j: { observations_done: number; observations_total: number }) {
  return j.observations_total ? j.observations_done / j.observations_total : 0;
}
