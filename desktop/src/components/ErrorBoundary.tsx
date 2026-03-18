import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** Optional fallback to show while recovering. Defaults to nothing. */
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
}

/**
 * Catches React rendering errors caused by DOM desync (e.g. the
 * "insertBefore" error triggered when external code or a browser
 * extension mutates the DOM under React's root).
 *
 * On error the boundary unmounts the subtree and immediately
 * re‑mounts it, which lets React rebuild the DOM from scratch.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn("[ErrorBoundary] Caught render error – recovering:", error.message, info.componentStack);
  }

  componentDidUpdate(_prevProps: Props, prevState: State) {
    // After we flip hasError → true and React unmounts the children,
    // schedule a reset so the children re‑mount on the next frame.
    if (this.state.hasError && !prevState.hasError) {
      requestAnimationFrame(() => {
        this.setState({ hasError: false });
      });
    }
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback ?? null;
    }
    return this.props.children;
  }
}
