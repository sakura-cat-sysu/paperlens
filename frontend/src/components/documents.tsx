import { useState, useRef, type ChangeEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Upload, X, Eye } from "lucide-react";
import {
  api,
  ApiError,
  queryKeys,
  type Document,
  type Schema,
} from "../api/client";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { ErrorMessage, Loading } from "./common";

export function UploadDocuments() {
  const input = useRef<HTMLInputElement>(null);
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: async (files: File[]) => {
      const result = {
        uploaded: 0,
        failures: [] as { filename: string; message: string }[],
      };
      for (const [index, file] of files.entries()) {
        try {
          if (file.size > 10 * 1024 * 1024)
            throw new Error("超过 10 MB，请选择更小的 PDF。");
          const body = new FormData();
          body.append("file", file);
          await api<Document>("/documents", { method: "POST", body });
          result.uploaded += 1;
        } catch (error) {
          const message =
            error instanceof Error ? error.message : "上传未完成，请重试。";
          result.failures.push({ filename: file.name, message });
          if (
            error instanceof ApiError &&
            [0, 401, 403].includes(error.status)
          ) {
            for (const remaining of files.slice(index + 1))
              result.failures.push({
                filename: remaining.name,
                message: `尚未上传：${message}`,
              });
            break;
          }
        }
      }
      if (result.uploaded)
        await client.invalidateQueries({ queryKey: queryKeys.documents });
      return result;
    },
  });
  function changed(event: ChangeEvent<HTMLInputElement>) {
    if (event.target.files) mutation.mutate(Array.from(event.target.files));
    event.target.value = "";
  }
  return (
    <div>
      <div className="upload-zone">
        <span className="upload-icon">
          <Upload size={23} aria-hidden="true" />
        </span>
        <div>
          <h3>添加研究文献</h3>
          <p>中英文文字型 PDF，每篇 ≤ 10 MB · 50 页</p>
        </div>
        <Button
          variant="outline"
          type="button"
          onClick={() => input.current?.click()}
          disabled={mutation.isPending}
        >
          {mutation.isPending ? "正在解析…" : "选择 PDF"}
        </Button>
        <input
          ref={input}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          className="sr-only"
          aria-label="上传 PDF 文献"
          onChange={changed}
          disabled={mutation.isPending}
        />
      </div>
      {!mutation.isPending && mutation.data && (
        <div className="mt-3">
          <p role="status" className="text-sm text-secondary">
            已添加 {mutation.data.uploaded} 份文献
            {mutation.data.failures.length
              ? `，${mutation.data.failures.length} 份未能添加。`
              : "。"}
          </p>
          {mutation.data.failures.length > 0 && (
            <ul className="mt-2 space-y-2">
              {mutation.data.failures.map((failure, index) => (
                <li key={index}>
                  <ErrorMessage
                    error={new Error(`${failure.filename}：${failure.message}`)}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <ErrorMessage error={mutation.error} />
    </div>
  );
}

export function DocumentPreview({
  document,
  onClose,
}: {
  document: Document | null;
  onClose: () => void;
}) {
  const [page, setPage] = useState(0);
  const detail = useQuery({
    queryKey: ["document", document?.id],
    queryFn: () => api<Schema["DocumentDetail"]>(`/documents/${document!.id}`),
    enabled: !!document,
  });
  const pages = detail.data?.pages ?? [];
  return (
    <Dialog
      open={!!document}
      onOpenChange={(open) => {
        if (!open) {
          onClose();
          setPage(0);
        }
      }}
      title={document?.filename ?? "文献预览"}
      description="按 PDF 物理页序查看提取正文。扫描图像不进行识别。"
    >
      <ErrorMessage error={detail.error} />
      {detail.isPending ? (
        <Loading />
      ) : (
        <>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <label className="field-label text-sm">
              物理页码
              <select
                value={page}
                onChange={(event) => setPage(Number(event.target.value))}
                className="w-32"
              >
                {pages.map((_, index) => (
                  <option value={index} key={index}>
                    第 {index + 1} 页
                  </option>
                ))}
              </select>
            </label>
            <a
              href={`/api/documents/${document?.id}/file`}
              className="text-link"
            >
              下载 PDF
            </a>
          </div>
          <pre className="source-text mt-4">
            {String(pages[page]?.text || "此页没有可提取文字。")}
          </pre>
        </>
      )}
    </Dialog>
  );
}

export function DocumentItem({
  document,
  selected,
  onToggle,
  onPreview,
  onDelete,
}: {
  document: Document;
  selected?: boolean;
  onToggle?: () => void;
  onPreview: () => void;
  onDelete?: () => void;
}) {
  return (
    <div className={`document-row ${selected ? "document-selected" : ""}`}>
      {onToggle ? (
        <label className="document-select">
          <input type="checkbox" checked={!!selected} onChange={onToggle} />
          <span className="sr-only">选择 {document.filename}</span>
        </label>
      ) : (
        <span className="file-icon">
          <FileText size={21} aria-hidden="true" />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <h3 className="break-words font-medium">{document.filename}</h3>
        <p className="mt-1 text-xs text-secondary">
          {document.page_count} 页 <span className="mx-1">·</span>
          {document.size_bytes < 1024 * 1024
            ? `${Math.max(1, Math.round(document.size_bytes / 1024))} KB`
            : `${(document.size_bytes / 1024 / 1024).toFixed(2)} MB`}{" "}
          <span className="mx-1">·</span>
          {document.text_chars.toLocaleString()} 字符
        </p>
        {document.warnings.map((warning) => (
          <p key={warning} className="mt-2 text-xs text-warning">
            {warning}
          </p>
        ))}
      </div>
      <Button
        variant="ghost"
        className="px-2"
        onClick={onPreview}
        aria-label={`预览 ${document.filename}`}
      >
        <Eye size={18} aria-hidden="true" />
      </Button>
      {onDelete && (
        <Button
          variant="ghost"
          className="px-2 text-danger"
          onClick={onDelete}
          aria-label={`删除 ${document.filename}`}
        >
          <X size={18} aria-hidden="true" />
        </Button>
      )}
    </div>
  );
}
