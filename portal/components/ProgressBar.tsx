export default function ProgressBar({ progress }: { progress: number }) {
  return (
    <div className="mt-1.5 h-1 w-full overflow-hidden rounded bg-zinc-800">
      <div className="h-full bg-indigo-400 transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
    </div>
  );
}
