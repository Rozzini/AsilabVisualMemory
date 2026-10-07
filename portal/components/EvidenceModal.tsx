"use client";

import { useEffect } from "react";
import { evidenceUrl } from "@/lib/api";
import type { Memory } from "@/types";

const LABELS: Record<string, string> = { before: "Before", mid: "During", after: "After" };
const GRID: Record<number, string> = { 1: "", 2: "md:grid-cols-2", 3: "md:grid-cols-3" };

export default function EvidenceModal({ memory, onClose }: { memory: Memory; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6" onClick={onClose}>
      <div
        className="max-h-full w-full max-w-6xl overflow-auto rounded-lg border border-zinc-800 bg-zinc-900 p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h3 className="font-medium">{memory.summary}</h3>
            <p className="mt-1 text-xs text-zinc-500">observation {memory.observation_id}</p>
          </div>
          <button onClick={onClose} className="text-zinc-400 hover:text-white" aria-label="Close">
            ✕
          </button>
        </div>
        <div className={`grid gap-3 ${GRID[memory.evidence.length] ?? "md:grid-cols-3"}`}>
          {memory.evidence.map((e) => (
            <figure key={e.url}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={evidenceUrl(e.url)} alt={e.name} className="w-full rounded border border-zinc-800" />
              <figcaption className="mt-1 text-center text-xs text-zinc-400">{LABELS[e.name] ?? e.name}</figcaption>
            </figure>
          ))}
        </div>
      </div>
    </div>
  );
}
