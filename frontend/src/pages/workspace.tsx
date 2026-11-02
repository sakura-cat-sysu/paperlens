import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Files, Plus, History, Layers3 } from "lucide-react";
import { Link } from "react-router-dom";
import {
  api,
  queryKeys,
  type Document,
  type Job,
  type Schema,
} from "../api/client";
import { Empty, ErrorMessage, JobRow, Loading } from "../components/common";
import { Button } from "../components/ui/button";

export function Workspace({ history = false }: { history?: boolean }) {
  const [page, setPage] = useState(0);
  const jobs = useQuery({
    queryKey: [...queryKeys.jobs, page],
    queryFn: () => api<Job[]>(`/analyses?offset=${page * 100}`),
    refetchInterval: 10000,
    placeholderData: keepPreviousData,
  });
  const documents = useQuery({
    queryKey: queryKeys.documents,
    queryFn: () => api<Document[]>("/documents"),
  });
  const usage = useQuery({
    queryKey: queryKeys.usage,
    queryFn: () => api<Schema["UsageView"]>("/usage"),
  });
  if (jobs.isPending) return <Loading />;
  const items = jobs.data ?? [];
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">
            {history ? "YOUR RESEARCH" : "RESEARCH WORKSPACE"}
          </span>
          <h1>{history ? "分析记录" : "把文献读在一起。"}</h1>
          <p>
            {history
              ? "每次探索，都有迹可循。"
              : "提出问题，比较观点，回到证据。"}
          </p>
        </div>
        <Button asChild>
          <Link to="/new">
            <Plus size={18} aria-hidden="true" />
            新建分析
          </Link>
        </Button>
      </div>
      <ErrorMessage error={jobs.error ?? documents.error ?? usage.error} />
      {!history && (
        <>
          <section className="workspace-intro">
            <div>
              <span className="eyebrow">从你的下一个问题开始</span>
              <h2>
                不同的文献，
                <br />
                同一个研究视角。
              </h2>
              <p>选择 2～3 篇中英文 PDF，围绕问题整理观点、共识与分歧。</p>
              <Link to="/new" className="text-link">
                开始一次分析 <ArrowUpRight size={17} aria-hidden="true" />
              </Link>
            </div>
            <div className="intro-illustration" aria-hidden="true">
              <div className="paper paper-back">
                <span>DOCUMENT 02</span>
                <i />
                <i />
                <i />
                <b>观点 B</b>
              </div>
              <div className="paper paper-front">
                <span>DOCUMENT 01</span>
                <i />
                <i />
                <b>观点 A</b>
                <i />
                <i />
              </div>
              <div className="evidence-seal">
                <Layers3 size={20} />
                可追溯原文
              </div>
            </div>
          </section>
          <div className="overview-strip">
            <Link to="/library">
              <Files size={20} aria-hidden="true" />
              <div>
                <strong>{documents.data?.length ?? "—"}</strong>
                <span>篇文献</span>
              </div>
              <ArrowUpRight size={16} aria-hidden="true" />
            </Link>
            <div>
              <History size={20} aria-hidden="true" />
              <div>
                <strong>{items.length}</strong>
                <span>次近期分析</span>
              </div>
            </div>
            <div>
              <Layers3 size={20} aria-hidden="true" />
              <div>
                <strong>{usage.data?.remaining ?? "—"}</strong>
                <span>次今日可用分析</span>
              </div>
            </div>
          </div>
        </>
      )}
      <section className="mt-10">
        <div className="section-heading">
          <h2>{history ? `分析记录 · 第 ${page + 1} 页` : "最近分析"}</h2>
          {!history && items.length > 5 && (
            <Link to="/history" className="text-link">
              查看全部 <ArrowUpRight size={16} aria-hidden="true" />
            </Link>
          )}
        </div>
        {items.length ? (
          <div className="job-list">
            {(history ? items : items.slice(0, 5)).map((job) => (
              <JobRow key={job.id} job={job} />
            ))}
          </div>
        ) : (
          <Empty
            title="还没有分析记录"
            description="从两篇文献和一个问题开始，报告会保存在这里。"
          />
        )}
        {history && (page > 0 || items.length === 100) && (
          <div className="mt-6 flex justify-end gap-3">
            <Button
              variant="outline"
              disabled={page === 0 || jobs.isFetching}
              onClick={() => setPage(page - 1)}
            >
              上一页
            </Button>
            <Button
              variant="outline"
              disabled={items.length < 100 || jobs.isFetching}
              onClick={() => setPage(page + 1)}
            >
              下一页
            </Button>
          </div>
        )}
      </section>
    </>
  );
}
