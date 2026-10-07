"use client";

import { api } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";
import ProgressBar from "./ProgressBar";

/** Shows the vision model state while it is not usable (first-run download, Ollama down...). */
export default function ModelStatus() {
  const { data } = usePoll(api.health, [], 3000);
  const model = data?.model;
  if (!model || model.status === "ready" || model.status === "external") return null;

  if (model.status === "downloading") {
    return (
      <div className="rounded-md bg-indigo-500/10 p-2 text-xs text-indigo-200">
        Downloading vision model {model.name}… {Math.round((model.progress ?? 0) * 100)}%
        <ProgressBar progress={model.progress ?? 0} />
        <p className="mt-1 text-indigo-300/70">First run only. Events are queued and analysed when it finishes.</p>
      </div>
    );
  }
  if (model.status === "checking") {
    return <div className="rounded-md bg-zinc-800 p-2 text-xs text-zinc-300">Checking vision model…</div>;
  }
  return (
    <div className="rounded-md bg-amber-500/10 p-2 text-xs text-amber-200">
      {model.status === "unavailable" ? "Vision model offline. Is Ollama running?" : model.message}
    </div>
  );
}
