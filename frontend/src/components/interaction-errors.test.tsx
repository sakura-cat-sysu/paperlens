import type { ReactNode } from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { UploadDocuments } from "./documents";
import { NewAnalysis } from "../pages/new-analysis";
import { Analysis } from "../pages/analysis";
import type { Document, JobDetail, Report } from "../api/client";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderWithClient(ui: ReactNode, entry = "/") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const documents: Document[] = [1, 2, 3, 4].map((index) => ({
  id: `00000000-0000-4000-8000-00000000000${index}`,
  filename: `paper-${index}.pdf`,
  size_bytes: 100,
  page_count: 2,
  text_chars: 100,
  warnings: [],
  created_at: "2026-11-03T00:00:00Z",
}));

test("a rejected PDF does not prevent later files from uploading", async () => {
  const attempted: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (_input, options) => {
      const file = (options?.body as FormData).get("file") as File;
      attempted.push(file.name);
      return file.name === "broken.pdf"
        ? json({ detail: "PDF 已损坏。" }, 422)
        : json(documents[0], 201);
    }),
  );
  const client = renderWithClient(<UploadDocuments />);
  const refresh = vi.spyOn(client, "invalidateQueries");
  fireEvent.change(screen.getByLabelText("上传 PDF 文献"), {
    target: {
      files: ["first.pdf", "broken.pdf", "last.pdf"].map(
        (name) => new File(["pdf"], name),
      ),
    },
  });
  expect(await screen.findByRole("status")).toHaveTextContent(
    "已添加 2 份文献，1 份未能添加。",
  );
  expect(attempted).toEqual(["first.pdf", "broken.pdf", "last.pdf"]);
  expect(screen.getByRole("alert")).toHaveTextContent(
    "broken.pdf：PDF 已损坏。",
  );
  expect(refresh).toHaveBeenCalledTimes(1);
});

test("an oversized file is rejected locally and the next PDF is still uploaded", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>(async () =>
    json(documents[0], 201),
  );
  vi.stubGlobal("fetch", fetch);
  renderWithClient(<UploadDocuments />);
  const oversized = new File(["large"], "oversized.pdf");
  Object.defineProperty(oversized, "size", { value: 10 * 1024 * 1024 + 1 });
  fireEvent.change(screen.getByLabelText("上传 PDF 文献"), {
    target: { files: [oversized, new File(["pdf"], "valid.pdf")] },
  });
  expect(await screen.findByRole("status")).toHaveTextContent(
    "已添加 1 份文献，1 份未能添加。",
  );
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("alert")).toHaveTextContent(
    "oversized.pdf：超过 10 MB",
  );
});

test("an expired session stops the batch and reports the unattempted files", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>(async () =>
    json({ detail: "请先登录。" }, 401),
  );
  vi.stubGlobal("fetch", fetch);
  renderWithClient(<UploadDocuments />);
  fireEvent.change(screen.getByLabelText("上传 PDF 文献"), {
    target: {
      files: ["first.pdf", "last.pdf"].map((name) => new File(["pdf"], name)),
    },
  });
  expect(await screen.findByRole("status")).toHaveTextContent(
    "已添加 0 份文献，2 份未能添加。",
  );
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(
    screen.getByText("last.pdf：尚未上传：请先登录。"),
  ).toBeInTheDocument();
});

function analysisApi({
  configured = true,
  remaining = 10,
  configError = false,
} = {}) {
  const fetch = vi.fn<typeof globalThis.fetch>(async (input) => {
    switch (String(input)) {
      case "/api/samples":
        return json([]);
      case "/api/documents":
        return json(documents);
      case "/api/models":
        return configError
          ? json({ detail: "配置暂时不可用。" }, 503)
          : json(
              configured
                ? [
                    {
                      id: "c1",
                      scope: "personal",
                      name: "主账号",
                      configured: true,
                      api_key_hint: "sk-…1234",
                      base_url: "https://api.deepseek.com",
                      model: "deepseek-flash",
                      updated_at: null,
                    },
                  ]
                : [],
            );
      case "/api/usage":
        return json({ used: 10 - remaining, limit: 10, remaining });
      default:
        throw new Error(`Unexpected request: ${input}`);
    }
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

async function fillAnalysis() {
  await screen.findByRole("checkbox", { name: "选择 paper-1.pdf" });
  fireEvent.click(screen.getByRole("checkbox", { name: "选择 paper-1.pdf" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "选择 paper-2.pdf" }));
  fireEvent.change(screen.getByLabelText("你想从这些文献中了解什么？"), {
    target: { value: "比较研究结论。" },
  });
}

test.each([
  [
    { configured: false },
    "还没有可用的模型配置，请联系管理员添加全局配置，或左下角账号设置里自行添加。",
  ],
  [{ remaining: 0 }, "今日次数已用完，额度每天北京时间 08:00 重置。"],
  [{ configError: true }, "暂时无法读取文献或分析配置，请刷新后重试。"],
])(
  "a disabled analysis explains its actual service or quota blocker: %j",
  async (options, reason) => {
    const fetch = analysisApi(options);
    renderWithClient(<NewAnalysis />);
    await fillAnalysis();
    expect(await screen.findByText(reason)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "开始分析" });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription(reason);
    expect(screen.queryByText("请选择至少 2 篇文献。")).not.toBeInTheDocument();
    fireEvent.submit(button.closest("form")!);
    expect(
      fetch.mock.calls.some(([, options]) => options?.method === "POST"),
    ).toBe(false);
  },
);

test("field guidance follows selection and question changes, then permits a valid analysis", async () => {
  analysisApi();
  renderWithClient(<NewAnalysis />);
  expect(await screen.findByText("请选择至少 2 篇文献。")).toBeInTheDocument();
  for (const index of [1, 2])
    fireEvent.click(
      screen.getByRole("checkbox", { name: `选择 paper-${index}.pdf` }),
    );
  expect(screen.getByText("请填写研究问题。")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("你想从这些文献中了解什么？"), {
    target: { value: "比较研究结论。" },
  });
  expect(screen.getByRole("button", { name: "开始分析" })).toBeEnabled();
  for (const index of [3, 4])
    fireEvent.click(
      screen.getByRole("checkbox", { name: `选择 paper-${index}.pdf` }),
    );
  expect(
    screen.getByText("一次最多选择 3 篇文献，请取消多余选择。"),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "开始分析" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: "选择 paper-4.pdf" }));
  expect(screen.getByRole("button", { name: "开始分析" })).toBeEnabled();
});

const emptyReport: Report = {
  question: "研究问题",
  model: "test-model",
  generated_at: "2026-11-03",
  documents: [],
  analyses: [],
  tasks: [],
  comparison: {
    summary: null,
    answers: [],
    agreements: [],
    disagreements: [],
    method_differences: [],
    reasons: [],
    unresolved_questions: [],
    warnings: [],
  },
};

test.each([false, true])(
  "draft retry follows the backend eligibility decision: %s",
  async (canRetry) => {
    const reason = "可用证据不足，请调整文献或问题后创建新分析。";
    const job: JobDetail = {
      id: "job-1",
      question: "研究问题",
      document_ids: documents.slice(0, 2).map((doc) => doc.id),
      status: "draft",
      progress: "草稿已保存",
      error: "",
      attempts: 1,
      created_at: "2026-11-03T00:00:00Z",
      updated_at: "2026-11-03T00:00:00Z",
      report: emptyReport,
      coverage_complete: false,
      can_retry: canRetry,
      retry_reason: canRetry ? "" : reason,
    };
    const fetch = vi.fn<typeof globalThis.fetch>(async () => json(job));
    vi.stubGlobal("fetch", fetch);
    renderWithClient(
      <Routes>
        <Route path="/analyses/:id" element={<Analysis />} />
      </Routes>,
      "/analyses/job-1",
    );
    const button = await screen.findByRole("button", {
      name: "重试未完成回答",
    });
    if (canRetry) {
      expect(button).toBeEnabled();
      expect(screen.queryByText(reason)).not.toBeInTheDocument();
    } else {
      expect(button).toBeDisabled();
      expect(button).toHaveAccessibleDescription(
        expect.stringContaining(reason),
      );
      expect(screen.getByRole("link", { name: "新建分析" })).toHaveAttribute(
        "href",
        "/new",
      );
      fireEvent.click(button);
      await waitFor(() =>
        expect(
          fetch.mock.calls.some(([, options]) => options?.method === "POST"),
        ).toBe(false),
      );
    }
  },
);
