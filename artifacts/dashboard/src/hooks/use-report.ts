import { useMutation } from "@tanstack/react-query";
import { api } from "./use-trading-client";

export interface ExportReportResult {
  report: string;
  char_count: number;
  line_count: number;
}

export function useExportReport() {
  return useMutation<ExportReportResult, Error, void>({
    mutationFn: async () => {
      const res = await api.get("/claude-report.txt?days=1", { responseType: "text" });
      const text = typeof res.data === "string" ? res.data : String(res.data);
      const lineCount = parseInt(res.headers["x-report-lines"] || "0", 10) || text.split("\n").length;
      const charCount = parseInt(res.headers["x-report-chars"] || "0", 10) || text.length;
      return { report: text, char_count: charCount, line_count: lineCount };
    },
  });
}