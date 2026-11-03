import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import type { ReactNode } from "react";
import { Library } from "./library";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.unstubAllGlobals();
});
function show(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}
function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function document(
  id: string,
  filename: string,
  size_bytes: number,
  created_at: string,
) {
  return {
    id,
    filename,
    size_bytes,
    created_at,
    page_count: 1,
    text_chars: 100,
    warnings: [],
  };
}
function filenames() {
  return screen
    .getAllByRole("heading", { level: 3 })
    .map((element) => element.textContent)
    .filter((text) => /\.pdf$/i.test(text ?? ""));
}

test("library search trims and ignores case, handles no results, and sorting preserves all documents", async () => {
  const documents = [
    document("a", "Alpha.pdf", 300, "2026-11-01T00:00:00Z"),
    document("b", "Beta.pdf", 100, "2026-11-03T00:00:00Z"),
    document("c", "Gamma.PDF", 200, "2026-11-02T00:00:00Z"),
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json(documents)),
  );
  show(<Library />);
  await screen.findByRole("heading", { name: "Alpha.pdf" });
  expect(filenames()).toEqual(["Beta.pdf", "Gamma.PDF", "Alpha.pdf"]);
  const search = screen.getByRole("searchbox", { name: "按文件名筛选文献" });
  fireEvent.change(search, { target: { value: " ALPHA " } });
  expect(filenames()).toEqual(["Alpha.pdf"]);
  fireEvent.change(search, { target: { value: "not-found" } });
  expect(screen.getByText("没有匹配的文献")).toBeInTheDocument();
  fireEvent.change(search, { target: { value: "" } });
  fireEvent.change(screen.getByRole("combobox", { name: "排序" }), {
    target: { value: "size" },
  });
  expect(filenames()).toEqual(["Alpha.pdf", "Gamma.PDF", "Beta.pdf"]);
  fireEvent.change(screen.getByRole("combobox", { name: "排序" }), {
    target: { value: "name" },
  });
  expect(filenames()).toEqual(["Alpha.pdf", "Beta.pdf", "Gamma.PDF"]);
});

test("recent sort puts a fractional-second timestamp after an earlier whole-second timestamp", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      json([
        document("whole", "older.pdf", 100, "2026-11-03T12:00:00Z"),
        document("fraction", "newer.pdf", 100, "2026-11-03T12:00:00.500000Z"),
      ]),
    ),
  );
  show(<Library />);
  await screen.findByRole("heading", { name: "newer.pdf" });
  expect(filenames()).toEqual(["newer.pdf", "older.pdf"]);
});
