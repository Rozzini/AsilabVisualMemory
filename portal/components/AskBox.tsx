"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Memory, QueryResponse, QueryScope } from "@/types";
import EvidenceModal from "./EvidenceModal";
import MemoryCard from "./MemoryCard";

const EXAMPLES = ["Where did I leave my keys?", "What changed on the desk?", "When was the mug removed?"];

export default function AskBox({ scope = {}, label }: { scope?: QueryScope; label: string }) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Memory | null>(null);

  async function ask(q: string) {
    if (!q.trim()) return;
    setQuestion(q);
    setBusy(true);
    setError(null);
    try {
      setResult(await api.query(q, scope));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
      <h2 className="text-sm font-medium text-zinc-300">Ask {label}</h2>
      <form
        className="mt-2 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Where did I leave my keys?"
          className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
        <button
          disabled={busy || !question.trim()}
          className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-400 disabled:opacity-50"
        >
          {busy ? "Thinking…" : "Ask"}
        </button>
      </form>
      {!result && !busy && (
        <div className="mt-2 flex flex-wrap gap-2">
          {EXAMPLES.map((q) => (
            <button key={q} onClick={() => ask(q)} className="rounded-full border border-zinc-700 px-2.5 py-1 text-xs text-zinc-400 hover:text-white">
              {q}
            </button>
          ))}
        </div>
      )}
      {error && <p className="mt-3 text-sm text-rose-400">{error}</p>}
      {result && (
        <div className="mt-4">
          <p className="text-base text-white">{result.answer}</p>
          {!result.used_llm && <p className="mt-1 text-xs text-zinc-500">(model unavailable — showing best keyword match)</p>}
          {result.memories.length > 0 && (
            <div className="mt-3 flex flex-col gap-2">
              <p className="text-xs uppercase tracking-wider text-zinc-500">Based on</p>
              {result.memories.map((m) => (
                <MemoryCard key={m.id} memory={m} showSource={!scope.device_id && !scope.job_id} highlight onOpen={setOpen} />
              ))}
            </div>
          )}
        </div>
      )}
      {open && <EvidenceModal memory={open} onClose={() => setOpen(null)} />}
    </section>
  );
}
