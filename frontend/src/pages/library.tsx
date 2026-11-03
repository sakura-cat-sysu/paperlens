import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, queryKeys, type Document } from "../api/client";
import {
  DocumentItem,
  DocumentPreview,
  UploadDocuments,
} from "../components/documents";
import { Empty, ErrorMessage, Loading } from "../components/common";
import { Dialog } from "../components/ui/dialog";
import { Button } from "../components/ui/button";

type SortKey = "recent" | "name" | "size";

export function Library() {
  const client = useQueryClient();
  const [preview, setPreview] = useState<Document | null>(null);
  const [deleting, setDeleting] = useState<Document | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("recent");
  const documents = useQuery({
    queryKey: queryKeys.documents,
    queryFn: () => api<Document[]>("/documents"),
  });
  const visible = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    const list = (documents.data ?? []).filter((document) =>
      keyword ? document.filename.toLowerCase().includes(keyword) : true,
    );
    return [...list].sort((a, b) => {
      if (sort === "name") return a.filename.localeCompare(b.filename, "zh-CN");
      if (sort === "size") return b.size_bytes - a.size_bytes;
      return b.created_at.localeCompare(a.created_at);
    });
  }, [documents.data, query, sort]);
  const mutation = useMutation({
    mutationFn: (id: string) =>
      api<void>(`/documents/${id}`, { method: "DELETE" }),
    onSuccess: async () => {
      setDeleting(null);
      await client.invalidateQueries({ queryKey: queryKeys.documents });
    },
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">YOUR SOURCE MATERIAL</span>
          <h1>文献库</h1>
          <p>管理原始文献，按页检查提取文字。</p>
        </div>
        <span className="text-sm text-secondary">
          {documents.data?.length ?? "—"} 篇文献
        </span>
      </div>
      <UploadDocuments />
      <ErrorMessage error={documents.error} />
      {documents.isPending ? (
        <Loading />
      ) : documents.data?.length ? (
        <>
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="按文件名筛选…"
              aria-label="按文件名筛选文献"
              className="w-full max-w-xs"
            />
            <label className="text-sm">
              排序{" "}
              <select
                value={sort}
                onChange={(event) => setSort(event.target.value as SortKey)}
                className="ml-2"
              >
                <option value="recent">最近添加</option>
                <option value="name">文件名</option>
                <option value="size">文件大小</option>
              </select>
            </label>
            {query.trim() && (
              <span role="status" className="text-sm text-secondary">
                找到 {visible.length} 篇
              </span>
            )}
          </div>
          {visible.length ? (
            <div className="surface mt-4">
              {visible.map((document) => (
                <DocumentItem
                  key={document.id}
                  document={document}
                  onPreview={() => setPreview(document)}
                  onDelete={() => {
                    mutation.reset();
                    setDeleting(document);
                  }}
                />
              ))}
            </div>
          ) : (
            <Empty
              title="没有匹配的文献"
              description="换个关键词，或清空筛选条件。"
              action={false}
            />
          )}
        </>
      ) : (
        <Empty
          title="文献库还是空的"
          description="添加中英文文字型 PDF，即可开始阅读与比较。"
          action={false}
        />
      )}
      <DocumentPreview document={preview} onClose={() => setPreview(null)} />
      <Dialog
        open={!!deleting}
        onOpenChange={(open) => {
          if (!open && !mutation.isPending) setDeleting(null);
        }}
        title="删除文献"
        description="将删除原始 PDF 与文献库中的正文。已有报告保留其分析时的证据快照；如需清除这些内容，请同时删除相关报告。"
      >
        <p className="break-words font-medium">{deleting?.filename}</p>
        <ErrorMessage error={mutation.error} />
        <div className="mt-6 flex justify-end gap-3">
          <Button
            variant="outline"
            onClick={() => setDeleting(null)}
            disabled={mutation.isPending}
          >
            取消
          </Button>
          <Button
            variant="destructive"
            disabled={mutation.isPending}
            onClick={() => deleting && mutation.mutate(deleting.id)}
          >
            {mutation.isPending ? "正在删除…" : "删除文献"}
          </Button>
        </div>
      </Dialog>
    </>
  );
}
