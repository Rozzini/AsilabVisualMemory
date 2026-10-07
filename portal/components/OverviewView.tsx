"use client";

import { api } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";
import AskBox from "./AskBox";
import Timeline from "./Timeline";

export default function OverviewView() {
  const memories = usePoll(() => api.memories({}, 50), [], 3000);

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-xl font-semibold">All memories</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Recent memories from every device and uploaded video. Pick a source on the left to see its full history.
        </p>
      </header>

      <AskBox label="your memory" />

      <section>
        <h2 className="mb-3 text-sm font-medium text-zinc-300">Recent</h2>
        <Timeline
          memories={memories.data}
          showSource
          empty={
            <>
              Nothing remembered yet. Start a device with <code className="text-zinc-300">visual-memory-agent --webcam</code>{" "}
              or upload a video.
            </>
          }
        />
      </section>
    </div>
  );
}
