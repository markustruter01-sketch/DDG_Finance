/**
 * Placeholder.tsx
 * Temporary landing shown for routes that are built in later stages.
 * Stage 4 replaces this with real content.
 */
export default function Placeholder({ stage, name }: { stage: number; name: string }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center max-w-md">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-indigo-100 mb-4">
          <span className="text-2xl">🚧</span>
        </div>
        <h1 className="text-xl font-semibold text-gray-900">{name}</h1>
        <p className="mt-2 text-sm text-gray-500">
          Coming in Stage {stage}. Routing and file structure are live — content builds here next.
        </p>
      </div>
    </div>
  );
}
