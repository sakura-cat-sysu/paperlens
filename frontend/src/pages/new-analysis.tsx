import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
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
import { SampleCollections, type SampleImport } from "../components/samples";

const scopeLabel = (scope: string) =>
  scope === "global" ? "全局" : scope === "environment" ? "服务器" : "个人";

export function NewAnalysis() {
  const location = useLocation();
  const initial = (location.state as { sample?: SampleImport } | null)?.sample;
  const navigate = useNavigate();
  const client = useQueryClient();
  const [selected, setSelected] = useState<string[]>(
    initial?.document_ids ?? [],
  );
  const [question, setQuestion] = useState(initial?.question ?? "");
  const [preview, setPreview] = useState<Document | null>(null);
  const [submission, setSubmission] = useState(crypto.randomUUID());
  const [configId, setConfigId] = useState("");
  const documents = useQuery({
    queryKey: queryKeys.documents,
    queryFn: () => api<Document[]>("/documents"),
  });
  const models = useQuery({
    queryKey: queryKeys.models,
    queryFn: () => api<Schema["ModelConfigView"][]>("/models"),
  });
  const usage = useQuery({
    queryKey: queryKeys.usage,
    queryFn: () => api<Schema["UsageView"]>("/usage"),
  });
  // 默认选中第一套可用配置，但允许在本次分析里换成别的。
  useEffect(() => {
    const options = models.data;
    if (!options?.length) return;
    if (options.some((option) => (option.id ?? "") === configId)) return;
    setConfigId(options[0].id ?? "");
  }, [models.data, configId]);
  const mutation = useMutation({
    mutationFn: () =>
      api<Job>("/analyses", {
        method: "POST",
        body: JSON.stringify({
          question,
          document_ids: selected,
          submission_id: submission,
          model_config_id: configId || null,
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
    if (!blockedReason && !mutation.isPending) mutation.mutate();
  }
  let blockedReason = "";
  if (documents.isPending || models.isPending || usage.isPending)
    blockedReason = "正在读取文献与分析配置，请稍候。";
  else if (documents.isError || models.isError || usage.isError)
    blockedReason = "暂时无法读取文献或分析配置，请刷新后重试。";
  else if (!models.data?.length)
    blockedReason =
      "还没有可用的模型配置，请联系管理员添加全局配置，或左下角账号设置里自行添加。";
  else if (usage.data?.remaining === 0)
    blockedReason = "今日次数已用完，额度每天北京时间 08:00 重置。";
  else if (selected.length < 2) blockedReason = "请选择至少 2 篇文献。";
  else if (selected.length > 3)
    blockedReason = "一次最多选择 3 篇文献，请取消多余选择。";
  else if (!question.trim()) blockedReason = "请填写研究问题。";
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
      <ErrorMessage error={documents.error ?? models.error ?? usage.error} />
      <SampleCollections
        onUse={(sample) => {
          setSelected(sample.document_ids);
          setQuestion(sample.question);
          setSubmission(crypto.randomUUID());
        }}
      />
      {initial && (
        <p role="status" className="notice mb-5">
          示例文献与问题已选好，可先预览原文，再开始分析。
        </p>
      )}
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
          <div className="model-picker">
            <label className="field-label" htmlFor="model-config">
              本次使用的模型配置
            </label>
            <select
              id="model-config"
              className="mt-2"
              value={configId}
              onChange={(event) => setConfigId(event.target.value)}
              disabled={!models.data?.length}
            >
              {models.data?.map((option) => (
                <option
                  key={option.id ?? "environment"}
                  value={option.id ?? ""}
                >
                  {scopeLabel(option.scope)} · {option.name}
                  {option.model ? `（${option.model}）` : ""}
                </option>
              ))}
            </select>
            <p className="field-help mt-2">
              不同配置可对应不同账号或服务商。想增加更多，请到「账号设置」。
            </p>
          </div>
          <p className="mt-5 text-sm leading-7 text-secondary">
            可以比较结论、分析机制，也可以要求提出待验证的方案。结果会按问题逐项回答，并关联原文证据。
          </p>
          <div className="privacy-note">
            <ShieldCheck size={19} aria-hidden="true" />
            <p>
              点击分析后，文献正文会发送给模型服务。文件与报告仅对你的账号开放，并会持续保存，直到你删除。
            </p>
          </div>
          <ErrorMessage error={mutation.error} />
          <Button
            type="submit"
            className="mt-6 w-full"
            disabled={!!blockedReason || mutation.isPending}
            aria-describedby={
              blockedReason ? "analysis-blocked-reason" : undefined
            }
          >
            {mutation.isPending ? "正在创建任务…" : "开始分析"}
            <ArrowRight size={17} aria-hidden="true" />
          </Button>
          {blockedReason && (
            <p
              id="analysis-blocked-reason"
              role="status"
              className="mt-3 text-sm text-secondary"
            >
              {blockedReason}
            </p>
          )}
        </section>
      </form>
      <DocumentPreview document={preview} onClose={() => setPreview(null)} />
    </>
  );
}
