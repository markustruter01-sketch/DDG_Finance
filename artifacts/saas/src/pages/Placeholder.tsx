/**
 * Placeholder.tsx
 * Shown for routes that are built in later stages.
 * Designed to sit naturally inside Shell (no full-screen override).
 */

import { Clock } from "lucide-react";

interface PlaceholderProps {
  stage: number;
  name: string;
}

export default function Placeholder({ stage, name }: PlaceholderProps) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[calc(100vh-10rem)] px-6 text-center">
      {/* Icon ring */}
      <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-zinc-800 border border-zinc-700 mb-5">
        <Clock className="w-6 h-6 text-zinc-500" />
      </div>

      {/* Page name */}
      <h1 className="text-zinc-100 text-xl font-semibold tracking-tight">{name}</h1>

      {/* Stage hint */}
      {stage > 0 && (
        <p className="mt-2 text-zinc-500 text-sm max-w-sm">
          Content for this page is built in{" "}
          <span className="text-indigo-400 font-medium">Stage {stage}</span>.
          Routing and shell are live — come back soon.
        </p>
      )}

      {/* Decorative grid */}
      <div className="mt-10 grid grid-cols-3 gap-3 w-full max-w-md opacity-30">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="h-16 rounded-lg bg-zinc-800 border border-zinc-700 animate-pulse"
            style={{ animationDelay: `${i * 120}ms` }}
          />
        ))}
      </div>
    </div>
  );
}
