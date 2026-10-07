import { Suspense } from "react";
import UploadView from "@/components/UploadView";

async function Upload({ params }: { params: PageProps<"/uploads/[jobId]">["params"] }) {
  const { jobId } = await params;
  return <UploadView key={jobId} id={jobId} />;
}

export default function UploadPage({ params }: PageProps<"/uploads/[jobId]">) {
  return (
    <Suspense fallback={<p className="text-sm text-zinc-500">Loading…</p>}>
      <Upload params={params} />
    </Suspense>
  );
}
