"use client";

import { useState } from "react";
import type { Memory } from "@/types";
import EvidenceModal from "./EvidenceModal";
import MemoryCard from "./MemoryCard";

interface Props {
  memories: Memory[] | null;
  showSource?: boolean;
  empty?: React.ReactNode;
}

export default function Timeline({ memories, showSource = false, empty }: Props) {
  const [open, setOpen] = useState<Memory | null>(null);

  if (memories === null) return <p className="text-sm text-zinc-500">Loading…</p>;
  if (memories.length === 0) return <div className="text-sm text-zinc-500">{empty ?? "No memories yet."}</div>;

  return (
    <>
      <div className="flex flex-col gap-2">
        {memories.map((m) => (
          <MemoryCard key={m.id} memory={m} showSource={showSource} onOpen={setOpen} />
        ))}
      </div>
      {open && <EvidenceModal memory={open} onClose={() => setOpen(null)} />}
    </>
  );
}
