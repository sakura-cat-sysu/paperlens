import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { Button } from "./ui/button";

type Props = {
  children: ReactNode;
  /** 页面级使用时标题更小，避免和页面标题打架。 */
  compact?: boolean;
};

type State = { error: Error | null };

/**
 * 渲染兜底：任何子组件抛错时显示可读信息，而不是整页白屏。
 * 只捕获渲染阶段错误；事件处理和异步请求错误仍由各页面自己处理。
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("render error:", error, info.componentStack);
  }

  reset = () => {
    this.setState({ error: null });
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div
        className={this.props.compact ? "page-error is-compact" : "page-error"}
        role="alert"
      >
        <span className="page-error-icon">
          <AlertTriangle
            size={this.props.compact ? 20 : 26}
            aria-hidden="true"
          />
        </span>
        <h1>页面出错了</h1>
        <p>
          {this.props.compact
            ? "这部分内容渲染失败，左侧导航仍然可用。"
            : "应用渲染时发生错误，可以重试或刷新页面。"}
        </p>
        <pre className="page-error-detail">
          {error.message || String(error)}
        </pre>
        <div className="page-error-actions">
          <Button type="button" onClick={this.reset}>
            <RotateCcw size={16} aria-hidden="true" />
            重试
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => window.location.reload()}
          >
            刷新页面
          </Button>
        </div>
      </div>
    );
  }
}
