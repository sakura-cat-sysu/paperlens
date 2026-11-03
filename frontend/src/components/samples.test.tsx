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
import { Library } from "../pages/library";
import { NewAnalysis } from "../pages/new-analysis";
import type { Document, Schema } from "../api/client";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.unstubAllGlobals();
});

const question = "比较检索增强的收益、风险与原文证据。";
const documents: Document[] = [1, 2].map((index) => ({
  id: `00000000-0000-4000-8000-00000000000${index}`,
  filename: `sample-${index}.pdf`,
  size_bytes: 1000,
  page_count: 12,
  text_chars: 10000,
  warnings: [],
  created_at: "2026-11-04T00:00:00Z",
}));
const collection: Schema["SampleCollectionView"] = {
  id: "example",
  title: "检索与幻觉",
  description: "两篇论文，一组研究问题。",
  question,
  papers: documents.map((document, index) => ({
    id: document.id,
    title: document.filename,
    authors: "Example authors",
    year: 2024,
    language: index ? "English" : "中文",
    filename: document.filename,
    page_count: 12,
    source_url: "https://example.org/paper",
    license: "CC BY 4.0",
    license_url: "https://creativecommons.org/licenses/by/4.0/",
  })),
};

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function setup(entry = "/new", failOnce = false) {
  let imported = false;
  let attempts = 0;
  const fetch = vi.fn<typeof globalThis.fetch>(async (input, options) => {
    const path = String(input);
    if (path === "/api/samples") return json([collection]);
    if (path === "/api/documents") return json(imported ? documents : []);
    if (path === "/api/usage") return json({ used: 0, limit: 5, remaining: 5 });
    if (path === "/api/capabilities") return json({ model_configured: true });
    if (path === "/api/samples/example/import" && options?.method === "POST") {
      attempts += 1;
      if (failOnce && attempts === 1)
        return json({ detail: "文献库剩余空间不足。" }, 409);
      imported = true;
      return json({
        document_ids: documents.map((document) => document.id),
        question,
        imported_count: 2,
        existing_count: 0,
      });
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/library" element={<Library />} />
          <Route path="/new" element={<NewAnalysis />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return fetch;
}

async function expectSelected() {
  await waitFor(() =>
    expect(screen.getByLabelText("你想从这些文献中了解什么？")).toHaveValue(
      question,
    ),
  );
  for (const document of documents)
    expect(
      await screen.findByRole("checkbox", {
        name: `选择 ${document.filename}`,
      }),
    ).toBeChecked();
  expect(screen.getByRole("button", { name: "开始分析" })).toBeEnabled();
}

test("sample selection fills papers and question without starting a model job", async () => {
  const fetch = setup();
  fireEvent.click(
    await screen.findByRole("button", { name: "使用示例：检索与幻觉" }),
  );
  await expectSelected();
  expect(
    fetch.mock.calls.filter(([, options]) => options?.method === "POST"),
  ).toHaveLength(1);
  expect(
    fetch.mock.calls.some(([path]) => String(path) === "/api/analyses"),
  ).toBe(false);
  expect(screen.getByRole("status")).toHaveTextContent(
    "点击开始分析将使用一次额度",
  );
});

test("library example action opens new analysis with the selected collection", async () => {
  setup("/library");
  fireEvent.click(
    await screen.findByRole("button", { name: "使用示例：检索与幻觉" }),
  );
  await expectSelected();
  expect(
    screen.getByRole("heading", { level: 1, name: "新建分析" }),
  ).toBeInTheDocument();
});

test("an import error is shown and a successful retry clears it", async () => {
  setup("/new", true);
  const button = await screen.findByRole("button", {
    name: "使用示例：检索与幻觉",
  });
  fireEvent.click(button);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "文献库剩余空间不足",
  );
  fireEvent.click(button);
  await expectSelected();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
