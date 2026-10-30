import { Component, type ErrorInfo, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  label?: string;
  autoRecoverMs?: number;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  private _recoverTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[ErrorBoundary${this.props.label ? ` – ${this.props.label}` : ""}]`, error, info.componentStack);
    if (this.props.autoRecoverMs && this.props.autoRecoverMs > 0) {
      this._recoverTimer = setTimeout(() => {
        this.setState({ hasError: false, error: null });
      }, this.props.autoRecoverMs);
    }
  }

  componentWillUnmount() {
    if (this._recoverTimer) clearTimeout(this._recoverTimer);
  }

  handleRetry = () => {
    if (this._recoverTimer) clearTimeout(this._recoverTimer);
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="glass panel" role="alert">
          <span className="status"><span className="dot problem" aria-hidden="true" />
            {this.props.label ? `${this.props.label} failed to load` : "This section failed to load"}</span>
          <p className="note" style={{ margin: 0 }}>{this.state.error?.message ?? "An unexpected error occurred"}</p>
          <div><button className="btn" onClick={this.handleRetry}><RefreshCw size={15} aria-hidden="true" /> Retry</button></div>
        </div>
      );
    }

    return this.props.children;
  }
}

