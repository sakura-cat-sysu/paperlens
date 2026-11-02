import { useState } from "react";
import { ArrowUpRight, Check, FileText } from "lucide-react";
import type { Finding, Report } from "../api/client";
import { Dialog } from "./ui/dialog";
import { Button } from "./ui/button";

const basisLabels: Record<string, string> = {
  reported: "论文报告",
  inference: "证据推导 · 待验证",
  proposal: "拟议方案 · 待验证",
};
const answerLabels: Record<string, string> = {
  answered: "已回答",
  partial: "部分回答",
  unanswered: "未完成",
};

export function FindingView({
  finding,
  report,
}: {
  finding: Finding;
  report: Report;
}) {
  const [source, setSource] = useState<string | null>(null);
  const [page, setPage] = useState<number | null>(null);
  const claims = report.analyses.flatMap((analysis) => analysis.claims);
  const claim = claims.find((value) => value.claim_id === source);
  const document = report.documents.find(
    (value) => value.document_id === claim?.document_id,
  );
  const selectedPage = document?.pages.find((value) => value.number === page);
  return (
    <div className="finding">
      <span className={`basis basis-${finding.basis}`}>
        {basisLabels[finding.basis] ?? finding.basis}
      </span>
      <p className="finding-text">{finding.text}</p>
      <div className="source-links">
        {finding.claim_ids.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => {
              setSource(id);
              setPage(null);
            }}
            aria-label={`查看 ${id} 的原文证据`}
          >
            <FileText size={12} aria-hidden="true" />
            {id}
            <ArrowUpRight size={11} aria-hidden="true" />
          </button>
        ))}
      </div>
      <Dialog
        open={!!source}
        onOpenChange={(open) => {
          if (!open) setSource(null);
        }}
        title={`${source ?? ""} · 原文证据`}
        description={`${document?.filename ?? ""} · PDF 物理页码从 1 开始`}
      >
        {finding.basis === "proposal" && (
          <p className="notice mb-5">
            引用说明方案的设计依据，不表示原论文已验证该方案有效。
          </p>
        )}
        <p className="font-medium">{claim?.claim}</p>
        {claim?.evidence.map((evidence, index) => (
          <div key={index} className="mt-5">
            <p className="mb-2 text-sm text-secondary">
              第 {evidence.page} 页 ·{" "}
              {evidence.verified ? "原文已匹配" : "未通过匹配"}
            </p>
            <blockquote className="quote">{evidence.quote}</blockquote>
            {!evidence.verified && (
              <p className="mt-2 text-sm text-danger">{evidence.reason}</p>
            )}
            <button
              className="text-link mt-3 text-sm"
              onClick={() => setPage(evidence.page)}
            >
              查看整页正文 <ArrowUpRight size={14} aria-hidden="true" />
            </button>
          </div>
        ))}
        {selectedPage && (
          <section className="mt-6">
            <h3 className="mb-3 font-medium">第 {page} 页 · 提取正文</h3>
            <pre className="source-text">{selectedPage.text}</pre>
          </section>
        )}
        <p className="mt-6 text-xs leading-6 text-secondary">
          原文匹配确认片段存在；观点解释与科学判断仍需结合研究设定复核。
        </p>
      </Dialog>
    </div>
  );
}

export function ReportView({
  report,
  complete,
}: {
  report: Report;
  complete: boolean;
}) {
  const [tab, setTab] = useState("answers");
  const comparison = report.comparison;
  const answered = comparison.answers.filter(
    (answer) => answer.status === "answered" && answer.statements.length,
  ).length;
  const tabs = [
    { id: "answers", name: "逐项回答" },
    { id: "comparison", name: "共识与分歧" },
    { id: "claims", name: "文献观点" },
    { id: "questions", name: "待研究问题" },
  ];
  return (
    <>
      <div className={`report-note ${complete ? "" : "report-note-draft"}`}>
        <Check size={18} aria-hidden="true" />
        <p>
          <strong className="font-medium">
            {complete
              ? `${answered}/${report.tasks.length} 项回答已生成`
              : `报告草稿 · ${answered}/${report.tasks.length} 项已回答`}
          </strong>
          <span>关键结论请结合原文复核。</span>
        </p>
      </div>
      <section className="report-summary">
        <span className="eyebrow">SYNTHESIS / 综合结论</span>
        {comparison.summary ? (
          <FindingView finding={comparison.summary} report={report} />
        ) : (
          <p className="mt-4 text-secondary">
            证据不足，尚未形成可追溯的综合结论。
          </p>
        )}
      </section>
      {comparison.warnings.map((warning) => (
        <p className="notice mt-4" key={warning}>
          {warning}
        </p>
      ))}
      <div className="report-tabs" aria-label="报告章节">
        {tabs.map((item) => (
          <Button
            key={item.id}
            variant="ghost"
            className={tab === item.id ? "report-tab-active" : ""}
            onClick={() => setTab(item.id)}
            aria-pressed={tab === item.id}
          >
            {item.name}
          </Button>
        ))}
      </div>
      <section
        className="report-body"
        aria-label={tabs.find((item) => item.id === tab)?.name}
      >
        {tab === "answers" &&
          report.tasks.map((task) => {
            const answer = comparison.answers.find(
              (value) => value.task_id === task.task_id,
            );
            return (
              <article key={task.task_id} className="answer-section">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <h2>
                    <span>{task.task_id}</span>
                    {task.title}
                  </h2>
                  <span className="text-sm text-secondary">
                    {answer ? answerLabels[answer.status] : "未完成"}
                  </span>
                </div>
                {answer?.statements.map((finding, index) => (
                  <FindingView key={index} finding={finding} report={report} />
                ))}
                {!answer?.statements.length && (
                  <p className="notice mt-4">此项尚未形成有出处的回答。</p>
                )}
                {answer?.limitations && (
                  <p className="notice mt-4">{answer.limitations}</p>
                )}
                {answer?.caveats && (
                  <p className="mt-4 text-sm leading-7 text-secondary">
                    适用限制：{answer.caveats}
                  </p>
                )}
              </article>
            );
          })}
        {tab === "comparison" &&
          (
            [
              ["共同观点", comparison.agreements],
              ["结论冲突", comparison.disagreements],
              ["机制差异与互补性", comparison.method_differences],
              ["可能的差异原因", comparison.reasons],
            ] as const
          ).map(([title, findings]) => (
            <article className="answer-section" key={title}>
              <h2>{title}</h2>
              {findings.length ? (
                findings.map((finding, index) => (
                  <FindingView key={index} finding={finding} report={report} />
                ))
              ) : (
                <p className="mt-4 text-sm text-secondary">
                  当前未形成有充分来源的{title}。
                </p>
              )}
            </article>
          ))}
        {tab === "claims" &&
          report.analyses.map((analysis) => (
            <article key={analysis.document_id} className="answer-section">
              <h2>
                <span>{analysis.document_id}</span>
                {analysis.filename}
              </h2>
              {analysis.warnings.map((warning) => (
                <p className="notice mt-4" key={warning}>
                  {warning}
                </p>
              ))}
              {analysis.claims.map((claim) => {
                const supported =
                  claim.evidence.length > 0 &&
                  claim.evidence.every((evidence) => evidence.verified);
                return (
                  <section key={claim.claim_id} className="claim-section">
                    <h3>
                      {claim.claim_id}{" "}
                      <span
                        className={supported ? "text-primary" : "text-warning"}
                      >
                        {supported ? "引文已匹配" : "待复核 · 未参与综合"}
                      </span>
                    </h3>
                    <p className="mt-3 leading-8">{claim.claim}</p>
                    {claim.explanation && (
                      <p className="mt-2 text-sm leading-7 text-secondary">
                        {claim.explanation}
                      </p>
                    )}
                    <details className="mt-3">
                      <summary>查看引用与页码</summary>
                      {claim.evidence.map((evidence, index) => (
                        <div key={index} className="mt-4">
                          <p className="mb-2 text-xs text-secondary">
                            第 {evidence.page} 页 ·{" "}
                            {evidence.verified
                              ? "原文已匹配"
                              : "页码与引用未核实"}
                          </p>
                          <blockquote className="quote">
                            {evidence.quote}
                          </blockquote>
                          {!evidence.verified && (
                            <p className="mt-2 text-sm text-warning">
                              {evidence.reason}
                            </p>
                          )}
                        </div>
                      ))}
                    </details>
                  </section>
                );
              })}
              {analysis.gaps.length > 0 && (
                <div className="mt-6">
                  <h3 className="text-sm font-semibold">本篇未充分涉及</h3>
                  <ul className="mt-2 list-disc space-y-2 pl-5 text-sm leading-7 text-secondary">
                    {analysis.gaps.map((gap) => (
                      <li key={gap}>{gap}</li>
                    ))}
                  </ul>
                </div>
              )}
            </article>
          ))}
        {tab === "questions" && (
          <article className="answer-section">
            <h2>尚待研究的问题</h2>
            {comparison.unresolved_questions.length ? (
              <ul className="mt-5 list-disc space-y-4 pl-5 leading-8">
                {comparison.unresolved_questions.map((question) => (
                  <li key={question}>{question}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-4 text-secondary">
                当前未提出额外问题，可查看各篇文献的适用范围。
              </p>
            )}
          </article>
        )}
      </section>
    </>
  );
}
