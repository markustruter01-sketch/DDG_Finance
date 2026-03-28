import { Component, type ErrorInfo, type ReactNode } from "react";
import { RefreshCw, AlertTriangle } from "lucide-react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  label?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[ErrorBoundary${this.props.label ? ` – ${this.props.label}` : ""}]`, error, info.componentStack);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-red-500/20 bg-red-500/5 px-6 py-8 text-center">
          <AlertTriangle className="h-6 w-6 text-red-400/70" />
          <div>
            <p className="text-sm font-semibold text-red-400">
              {this.props.label ? `${this.props.label} failed to load` : "This section failed to load"}
            </p>
            <p className="text-[11px] text-muted-foreground mt-1 max-w-xs">
              {this.state.error?.message ?? "An unexpected error occurred"}
            </p>
          </div>
          <button
            onClick={this.handleRetry}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-500/30 text-red-400 text-[11px] hover:bg-red-500/10 transition-all"
          >
            <RefreshCw className="h-3 w-3" /> Retry
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

export function SafeSection({
  children,
  label,
}: {
  children: ReactNode;
  label?: string;
}) {
  return <ErrorBoundary label={label}>{children}</ErrorBoundary>;
}
