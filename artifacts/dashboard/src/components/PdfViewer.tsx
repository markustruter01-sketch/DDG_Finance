import { useState, useEffect, useRef, useCallback } from "react";
import * as pdfjsLib from "pdfjs-dist";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from "lucide-react";

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.mjs",
  import.meta.url
).toString();

interface PdfViewerProps {
  url: string;
}

export function PdfViewer({ url }: PdfViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [pdf, setPdf] = useState<pdfjsLib.PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [scale, setScale] = useState(1.4);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const renderTaskRef = useRef<any>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const loadingTask = pdfjsLib.getDocument(url);
    loadingTask.promise
      .then((doc) => {
        if (!cancelled) {
          setPdf(doc);
          setTotalPages(doc.numPages);
          setPage(1);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError("Failed to load PDF");
          setLoading(false);
          console.error("PDF load error:", err);
        }
      });
    return () => { cancelled = true; };
  }, [url]);

  const renderPage = useCallback(async () => {
    if (!pdf || !canvasRef.current) return;
    if (renderTaskRef.current) {
      renderTaskRef.current.cancel();
    }
    try {
      const p = await pdf.getPage(page);
      const viewport = p.getViewport({ scale });
      const canvas = canvasRef.current;
      canvas.height = viewport.height;
      canvas.width = viewport.width;
      const ctx = canvas.getContext("2d")!;
      const task = p.render({ canvasContext: ctx, viewport });
      renderTaskRef.current = task;
      await task.promise;
    } catch (err: any) {
      if (err?.name !== "RenderingCancelledException") {
        console.error("Render error:", err);
      }
    }
  }, [pdf, page, scale]);

  useEffect(() => {
    renderPage();
  }, [renderPage]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-muted-foreground text-sm animate-pulse">Loading PDF...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-red-400 text-sm">{error}</div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex items-center justify-center gap-4 px-4 py-2 border-b border-white/10 bg-slate-900/80 shrink-0">
        <button
          onClick={() => setScale((s) => Math.max(0.5, s - 0.2))}
          disabled={scale <= 0.5}
          className="p-1.5 rounded-lg text-muted-foreground hover:text-white hover:bg-white/10 transition-colors disabled:opacity-30"
        >
          <ZoomOut className="h-4 w-4" />
        </button>
        <span className="text-xs text-muted-foreground font-mono min-w-[4ch] text-center">
          {Math.round(scale * 100)}%
        </span>
        <button
          onClick={() => setScale((s) => Math.min(3, s + 0.2))}
          disabled={scale >= 3}
          className="p-1.5 rounded-lg text-muted-foreground hover:text-white hover:bg-white/10 transition-colors disabled:opacity-30"
        >
          <ZoomIn className="h-4 w-4" />
        </button>

        <div className="h-4 w-px bg-white/10" />

        <button
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={page <= 1}
          className="p-1.5 rounded-lg text-muted-foreground hover:text-white hover:bg-white/10 transition-colors disabled:opacity-30"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span className="text-xs text-muted-foreground font-mono">
          {page} / {totalPages}
        </span>
        <button
          onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          disabled={page >= totalPages}
          className="p-1.5 rounded-lg text-muted-foreground hover:text-white hover:bg-white/10 transition-colors disabled:opacity-30"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      <div ref={containerRef} className="flex-1 overflow-auto flex justify-center p-4 bg-slate-950/50">
        <canvas ref={canvasRef} className="shadow-2xl" />
      </div>
    </div>
  );
}
