import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Check,
  LoaderCircle,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, queryKeys, type JobDetail } from "../api/client";
import {
  ErrorMessage,
  formatDate,
  Loading,
  Status,
} from "../components/common";
import { Button } from "../components/ui/button";
import { Dialog } from "../components/ui/dialog";
import { ReportView } from "../components/report";

export function Analysis() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [deleting, setDeleting] = useState(false);
  const job = useQuery({
    queryKey: queryKeys.job(id),
    queryFn: () => api<JobDetail>(`/analyses/${id}`),
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.status ?? "")
        ? 10000
        : false,
  });
  const status = job.data?.status;
  useEffect(() => {
    if (!["queued", "running"].includes(status ?? "")) return;
    const events = new EventSource(`/api/analyses/${id}/events`);
    events.onmessage = () => {
      void client.invalidateQueries({ queryKey: queryKeys.job(id) });
    };
    return () => events.close();
  }, [id, status, client]);
  const retry = useMutation({
    mutationFn: () => api(`/analyses/${id}/retry`, { method: "POST" }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: queryKeys.job(id) });
      await client.invalidateQueries({ queryKey: queryKeys.usage });
    },
  });
  const remove = useMutation({
    mutationFn: () => api(`/analyses/${id}`, { method: "DELETE" }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: queryKeys.jobs });
      navigate("/history");
    },
  });
  if (job.isPending) return <Loading />;
  if (!job.data)
    return (
      <>
        <Link to="/history" className="text-link">
          <ArrowLeft size={16} />
          返回分析记录
        </Link>
        <ErrorMessage error={job.error} />
      </>
    );
  const value = job.data;
  const active = ["queued", "running"].includes(value.status);
  return (
    <>
      <Link to="/history" className="text-link mb-6 text-sm">
        <ArrowLeft size={15} aria-hidden="true" />
        分析记录
      </Link>
      <div className="report-heading">
        <div className="flex flex-wrap items-center gap-3">
          <Status status={value.status} />
          <span className="text-xs text-secondary">
            {formatDate(value.created_at)} · {value.document_ids.length} 篇文献
          </span>
        </div>
        <h1>{value.question}</h1>
        <div className="mt-5 flex flex-wrap items-center justify-between gap-4">
          <p className="text-sm text-secondary">
            {value.report
              ? `模型：${value.report.model}`
              : "任务与进度会自动保存，可随时离开并返回。"}
          </p>
          <div className="flex gap-2">
            {["failed", "draft"].includes(value.status) && (
              <Button
                variant="outline"
                onClick={() => retry.mutate()}
                disabled={retry.isPending}
              >
                <RotateCcw size={16} aria-hidden="true" />
                {retry.isPending
                  ? "正在提交…"
                  : value.status === "draft"
                    ? "重试未完成回答"
                    : "继续分析"}
              </Button>
            )}
            {!active && (
              <Button
                variant="ghost"
                className="text-secondary"
                onClick={() => setDeleting(true)}
                aria-label="删除分析报告"
              >
                <Trash2 size={17} aria-hidden="true" />
              </Button>
            )}
          </div>
        </div>
      </div>
      <ErrorMessage error={job.error ?? retry.error} />
      {value.error && <ErrorMessage error={new Error(value.error)} />}
      {active && (
        <section className="analysis-progress" role="status">
          <span className="progress-orbit">
            <LoaderCircle
              size={34}
              className="animate-spin"
              aria-hidden="true"
            />
          </span>
          <h2>
            {value.status === "queued"
              ? "分析已加入队列"
              : "正在连接文献中的线索"}
          </h2>
          <p className="mt-3 break-words text-secondary">{value.progress}</p>
          <div className="progress-steps">
            <span>
              <Check size={14} aria-hidden="true" />
              文献已保存
            </span>
            <span>问题拆解</span>
            <span>观点与引文校验</span>
            <span>逐项回答</span>
          </div>
          <p className="mt-8 text-xs text-secondary">
            分析时间取决于文献长度和模型响应。刷新页面不会重新创建任务。
          </p>
        </section>
      )}
      {value.report && (
        <ReportView
          key={value.id}
          report={value.report}
          complete={value.coverage_complete}
        />
      )}
      <Dialog
        open={deleting}
        onOpenChange={(open) => {
          if (!remove.isPending) setDeleting(open);
        }}
        title="删除分析报告"
        description="将删除此任务、报告和阶段结果。文献库中的原始 PDF 会保留。此操作无法撤销。"
      >
        <ErrorMessage error={remove.error} />
        <div className="flex justify-end gap-3">
          <Button
            variant="outline"
            onClick={() => setDeleting(false)}
            disabled={remove.isPending}
          >
            取消
          </Button>
          <Button
            variant="destructive"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
          >
            {remove.isPending ? "正在删除…" : "删除报告"}
          </Button>
        </div>
      </Dialog>
    </>
  );
}
