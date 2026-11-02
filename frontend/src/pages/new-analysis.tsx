import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
  api,
  queryKeys,
  type Document,
  type Job,
  type Schema,
} from "../api/client";
import {
  DocumentItem,
  DocumentPreview,
  UploadDocuments,
} from "../components/documents";
import { Empty, ErrorMessage } from "../components/common";
import { Button } from "../components/ui/button";

export function NewAnalysis() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [selected, setSelected] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const [preview, setPreview] = useState<Document | null>(null);
  const [submission, setSubmission] = useState(crypto.randomUUID());
  const documents = useQuery({
    queryKey: queryKeys.documents,
    queryFn: () => api<Document[]>("/documents"),
  });
  const config = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<Schema["Capabilities"]>("/capabilities"),
  });
  const usage = useQuery({
    queryKey: queryKeys.usage,
    queryFn: () => api<Schema["UsageView"]>("/usage"),
  });
  const mutation = useMutation({
    mutationFn: () =>
      api<Job>("/analyses", {
        method: "POST",
        body: JSON.stringify({
          question,
          document_ids: selected,
          submission_id: submission,
        }),
      }),
    onSuccess: async (job) => {
      await client.invalidateQueries({ queryKey: queryKeys.jobs });
      await client.invalidateQueries({ queryKey: queryKeys.usage });
      navigate(`/analyses/${job.id}`);
    },
  });
  function toggle(id: string) {
    setSelected((values) =>
      values.includes(id)
        ? values.filter((value) => value !== id)
        : [...values, id],
    );
    setSubmission(crypto.randomUUID());
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    mutation.mutate();
  }
  const valid =
    selected.length >= 2 &&
    selected.length <= 3 &&
    !!question.trim() &&
    config.data?.model_configured &&
    !!usage.data?.remaining;
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">A QUESTION WORTH EXPLORING</span>
          <h1>新建分析</h1>
          <p>选好文献，让一个问题把它们联系起来。</p>
        </div>
        <span className="text-sm text-secondary">
          今日剩余 {usage.data?.remaining ?? "—"} 次
        </span>
      </div>
      <ErrorMessage error={documents.error ?? config.error ?? usage.error} />
      <form onSubmit={submit} className="analysis-form">
        <section>
          <div className="section-heading">
            <h2>
              <span className="step-number">01</span>选择文献
            </h2>
            <span
              className={
                selected.length > 3
                  ? "text-danger text-sm"
                  : "text-secondary text-sm"
              }
            >
              已选 {selected.length} / 3 篇
            </span>
          </div>
          <UploadDocuments />
          <div className="mt-5">
            {documents.data?.length ? (
              documents.data.map((document) => (
                <DocumentItem
                  key={document.id}
                  document={document}
                  selected={selected.includes(document.id)}
                  onToggle={() => toggle(document.id)}
                  onPreview={() => setPreview(document)}
                />
              ))
            ) : (
              <Empty
                title="先添加你的文献"
                description="上传后可预览提取正文，再选择 2～3 篇进行比较。"
                action={false}
              />
            )}
          </div>
        </section>
        <section className="question-panel">
          <h2>
            <span className="step-number">02</span>提出研究问题
          </h2>
          <label className="field-label mt-6" htmlFor="question">
            你想从这些文献中了解什么？
          </label>
          <textarea
            id="question"
            value={question}
            onChange={(event) => {
              setQuestion(event.target.value);
              setSubmission(crypto.randomUUID());
            }}
            maxLength={2000}
            rows={7}
            placeholder="例如：生成式 AI 在什么条件下能改善大学生的学习效果？不同研究有哪些共识和局限？"
            required
          />
          <p className="mt-2 text-right text-xs text-secondary">
            {question.length} / 2,000
          </p>
          <p className="mt-5 text-sm leading-7 text-secondary">
            可以比较结论、分析机制，也可以要求提出待验证的方案。结果会按问题逐项回答，并关联原文证据。
          </p>
          <div className="privacy-note">
            <ShieldCheck size={19} aria-hidden="true" />
            <p>
              点击分析后，文献正文会发送给模型服务。文件与报告仅对你的账号开放，并会持续保存，直到你删除。
            </p>
          </div>
          {config.data && !config.data.model_configured && (
            <p role="alert" className="error-message">
              模型服务尚未配置，请联系管理员。
            </p>
          )}
          {usage.data?.remaining === 0 && (
            <p role="alert" className="error-message">
              今日次数已用完，额度将在 UTC 零点重置。
            </p>
          )}
          <ErrorMessage error={mutation.error} />
          <Button
            type="submit"
            className="mt-6 w-full"
            disabled={!valid || mutation.isPending}
          >
            {mutation.isPending ? "正在创建任务…" : "开始分析"}
            <ArrowRight size={17} aria-hidden="true" />
          </Button>
          {!valid && (
            <p className="mt-3 text-xs text-secondary">
              请选择 2～3 篇文献并填写研究问题。
            </p>
          )}
        </section>
      </form>
      <DocumentPreview document={preview} onClose={() => setPreview(null)} />
    </>
  );
}
