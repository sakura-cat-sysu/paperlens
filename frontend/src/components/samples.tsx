import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, BookOpen } from "lucide-react";
import { api, queryKeys, type Schema } from "../api/client";
import { ErrorMessage } from "./common";
import { Button } from "./ui/button";

export type SampleImport = Schema["SampleImportResult"];

export function SampleCollections({
  onUse,
}: {
  onUse: (result: SampleImport) => void;
}) {
  const client = useQueryClient();
  const [result, setResult] = useState<SampleImport | null>(null);
  const collections = useQuery({
    queryKey: ["sample-collections"],
    queryFn: () => api<Schema["SampleCollectionView"][]>("/samples"),
  });
  const mutation = useMutation({
    mutationFn: (id: string) =>
      api<SampleImport>(`/samples/${id}/import`, { method: "POST" }),
    onMutate: () => setResult(null),
    onSuccess: async (value) => {
      await client.invalidateQueries({ queryKey: queryKeys.documents });
      setResult(value);
      onUse(value);
    },
  });
  if (collections.isPending) return null;
  if (!collections.isError && !collections.data?.length) return null;
  return (
    <section className="sample-panel" aria-label="示例文献">
      <div className="sample-heading">
        <BookOpen size={22} aria-hidden="true" />
        <div>
          <h2>没有准备论文？先选一组示例</h2>
          <p>添加原文并填入研究问题，先预览，再点击开始分析。</p>
        </div>
      </div>
      <ErrorMessage error={collections.error ?? mutation.error} />
      {collections.isError && (
        <Button
          type="button"
          variant="outline"
          className="mt-4"
          onClick={() => collections.refetch()}
        >
          重新读取示例
        </Button>
      )}
      <div className="sample-grid">
        {collections.data?.map((collection) => (
          <article className="sample-card" key={collection.id}>
            <h3>{collection.title}</h3>
            <p className="sample-description">{collection.description}</p>
            <ul className="sample-papers">
              {collection.papers.map((paper) => (
                <li key={paper.id}>
                  <span>
                    {paper.language} · {paper.page_count} 页
                  </span>
                  <a
                    href={paper.source_url}
                    target="_blank"
                    rel="noreferrer"
                    title={paper.title}
                  >
                    {paper.title}
                    <ArrowUpRight size={12} aria-hidden="true" />
                  </a>
                </li>
              ))}
            </ul>
            <details className="sample-credits">
              <summary>来源与授权</summary>
              {collection.papers.map((paper) => (
                <p key={paper.id}>
                  {paper.title} · {paper.authors} · {paper.year} ·{" "}
                  <a href={paper.license_url} target="_blank" rel="noreferrer">
                    {paper.license}
                  </a>
                </p>
              ))}
              <p>保留原始 PDF 与作者署名；推荐问题由文镜整理。</p>
            </details>
            <Button
              type="button"
              variant="outline"
              className="mt-auto w-full"
              disabled={mutation.isPending}
              aria-label={`使用示例：${collection.title}`}
              onClick={() => mutation.mutate(collection.id)}
            >
              {mutation.isPending && mutation.variables === collection.id
                ? "正在添加文献…"
                : "使用这组示例"}
            </Button>
          </article>
        ))}
      </div>
      {result && (
        <p role="status" className="sample-result">
          已添加 {result.imported_count} 篇，复用已有 {result.existing_count}{" "}
          篇。 文献与研究问题已选好，点击开始分析将使用一次额度。
        </p>
      )}
    </section>
  );
}
