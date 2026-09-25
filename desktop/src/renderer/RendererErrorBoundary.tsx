import { Component, type ErrorInfo, type ReactNode } from "react";
import { useTranslation } from "./i18n";

interface RendererErrorBoundaryProps {
  children: ReactNode;
  name: string;
}

interface RendererErrorBoundaryState {
  failed: boolean;
}

class Boundary extends Component<
  RendererErrorBoundaryProps & { title: string; retryLabel: string },
  RendererErrorBoundaryState
> {
  state: RendererErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): RendererErrorBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Keep the original error and component stack available to DevTools and
    // the host diagnostic console while the local surface remains usable.
    console.error(`[uthcode.renderer:${this.props.name}]`, error, info.componentStack);
    const api = (globalThis as unknown as { uthcode?: { reportRendererDiagnostic?: (boundary: string) => Promise<void> } }).uthcode;
    const report = api?.reportRendererDiagnostic?.(this.props.name);
    void report?.catch(() => undefined);
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return <section className="renderer-error-boundary" role="alert" aria-live="polite">
      <span>{this.props.title}</span>
      <button type="button" onClick={() => this.setState({ failed: false })}>{this.props.retryLabel}</button>
    </section>;
  }
}

/** Isolate a failed renderer region without resetting the session state. */
export function RendererErrorBoundary({ children, name }: RendererErrorBoundaryProps) {
  const { t } = useTranslation();
  return <Boundary name={name} title={t("rendererAreaError")} retryLabel={t("retry")}>{children}</Boundary>;
}
