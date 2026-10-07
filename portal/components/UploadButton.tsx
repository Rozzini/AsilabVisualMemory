"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, triggerRefresh } from "@/lib/api";

export default function UploadButton() {
  const input = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const job = await api.upload(file);
      triggerRefresh();
      router.push(`/uploads/${job.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div>
      <input
        ref={input}
        type="file"
        accept="video/*"
        className="hidden"
        onChange={(e) => onFile(e.target.files?.[0])}
      />
      <button
        onClick={() => input.current?.click()}
        disabled={busy}
        className="w-full rounded-md bg-indigo-500 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-400 disabled:opacity-60"
      >
        {busy ? "Uploading…" : "Upload video"}
      </button>
      {error && <p className="mt-1 text-xs text-rose-400">{error}</p>}
    </div>
  );
}
