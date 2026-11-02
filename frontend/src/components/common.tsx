import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  Clock3,
  LoaderCircle,
} from "lucide-react";
import { Link } from "react-router-dom";
import type { Job } from "../api/client";
import { Button } from "./ui/button";

export const statusLabels: Record<string, string> = {
  queued: "等待分析",
  running: "正在分析",
  completed: "回答已生成",
  draft: "报告草稿",
  failed: "分析未完成",
};

export function Status({ status }: { status: string }) {
  const Icon =
    status === "running"
      ? LoaderCircle
      : status === "completed"
        ? CheckCircle2
        : status === "queued"
          ? Clock3
          : AlertCircle;
  return (
    <span className={`status status-${status}`}>
      <Icon
        size={14}
        className={status === "running" ? "animate-spin" : ""}
        aria-hidden="true"
      />
      {statusLabels[status] ?? status}
    </span>
  );
}

export function ErrorMessage({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="error-message">
      <AlertCircle size={18} aria-hidden="true" />
      {error instanceof Error ? error.message : "操作未完成，请重试。"}
    </p>
  );
}

export function Loading() {
  return (
    <div className="empty-state" role="status">
      <LoaderCircle className="animate-spin text-primary" aria-hidden="true" />
      <p>正在读取…</p>
    </div>
  );
}

export function Empty({
  title,
  description,
  action = true,
}: {
  title: string;
  description: string;
  action?: boolean;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <BookOpen size={26} aria-hidden="true" />
      </span>
      <h2>{title}</h2>
      <p>{description}</p>
      {action && (
        <Button asChild>
          <Link to="/new">新建分析</Link>
        </Button>
      )}
    </div>
  );
}

export function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function JobRow({ job }: { job: Job }) {
  return (
    <Link to={`/analyses/${job.id}`} className="job-row">
      <div className="min-w-0">
        <h3 className="line-clamp-2">{job.question}</h3>
        <p className="mt-2 text-sm text-secondary">
          {job.document_ids.length} 篇文献 <span className="mx-2">·</span>
          {formatDate(job.created_at)}
        </p>
      </div>
      <Status status={job.status} />
    </Link>
  );
}
