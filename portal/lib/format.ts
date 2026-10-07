export function videoTime(seconds: number | null | undefined): string {
  if (seconds == null) return "";
  const s = Math.floor(seconds);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const EVENT_STYLES: Record<string, string> = {
  object_moved: "bg-blue-500/15 text-blue-300 ring-blue-500/30",
  object_added: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  object_removed: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  person_entered: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  person_left: "bg-orange-500/15 text-orange-300 ring-orange-500/30",
  person_activity: "bg-yellow-500/15 text-yellow-300 ring-yellow-500/30",
  lighting_change: "bg-sky-500/15 text-sky-300 ring-sky-500/30",
  camera_moved: "bg-fuchsia-500/15 text-fuchsia-300 ring-fuchsia-500/30",
  scene_change: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  baseline: "bg-zinc-500/15 text-zinc-300 ring-zinc-500/30",
  other: "bg-zinc-500/15 text-zinc-300 ring-zinc-500/30",
};

export const eventLabel = (t: string) => t.replace(/_/g, " ");
