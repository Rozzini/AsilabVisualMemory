import { Suspense } from "react";
import DeviceView from "@/components/DeviceView";

async function Device({ params }: { params: PageProps<"/devices/[id]">["params"] }) {
  const deviceId = decodeURIComponent((await params).id);
  return <DeviceView key={deviceId} id={deviceId} />;
}

export default function DevicePage({ params }: PageProps<"/devices/[id]">) {
  return (
    <Suspense fallback={<p className="text-sm text-zinc-500">Loading…</p>}>
      <Device params={params} />
    </Suspense>
  );
}
