import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "../app";
import { AuthProvider } from "../auth";
import { setCsrfToken, type Schema } from "../api/client";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  setCsrfToken("");
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

const guest: Schema["UserView"] = {
  id: "guest-id",
  email: "guest@guest.invalid",
  is_admin: false,
  is_guest: true,
};
const regular: Schema["UserView"] = {
  id: "regular-id",
  email: "reader@example.com",
  is_admin: false,
  is_guest: false,
};
function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function setup({
  enabled = true,
  failOnce = false,
  initialGuest = false,
  remaining = 10,
} = {}) {
  let current: Schema["UserView"] | null = initialGuest ? guest : null;
  let entries = 0;
  const fetch = vi.fn<typeof globalThis.fetch>(async (input) => {
    const path = String(input);
    if (path === "/api/auth/me")
      return current
        ? json({ user: current, csrf_token: "csrf" })
        : json({ detail: "请先登录。" }, 401);
    if (path === "/api/capabilities")
      return json({
        allow_guests: enabled,
        guest_daily_analyses: 10,
        allow_registration: false,
        model_configured: true,
      });
    if (path === "/api/auth/guest") {
      entries += 1;
      if (failOnce && entries === 1)
        return json({ detail: "游客创建过于频繁，请稍后重试。" }, 429);
      current = guest;
      return json({ user: guest, csrf_token: "guest-csrf" });
    }
    if (path === "/api/auth/login") {
      current = regular;
      return json({ user: regular, csrf_token: "regular-csrf" });
    }
    if (path === "/api/usage")
      return json({
        used: current?.is_guest ? 10 - remaining : 0,
        limit: current?.is_guest ? 10 : 20,
        remaining: current?.is_guest ? remaining : 20,
      });
    if (
      path === "/api/documents" ||
      path === "/api/samples" ||
      path.startsWith("/api/analyses?")
    )
      return json([]);
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetch);
  window.history.replaceState({}, "", initialGuest ? "/new" : "/login");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </QueryClientProvider>,
  );
  return fetch;
}

test("guest entry needs no form fields and opens an isolated workspace with ten attempts", async () => {
  const fetch = setup();
  fireEvent.click(await screen.findByRole("button", { name: "一键游客体验" }));
  expect(
    await screen.findByRole("heading", { name: "新建分析", level: 1 }),
  ).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByLabelText("游客空间与额度")).toHaveTextContent(
      "今日剩余 10 / 10 次分析",
    ),
  );
  expect(screen.queryByText(guest.email)).not.toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "邀请码" }),
  ).not.toBeInTheDocument();
  expect(
    fetch.mock.calls
      .filter(([, options]) => options?.method === "POST")
      .map(([path]) => path),
  ).toEqual(["/api/auth/guest"]);
});

test("guest failure is shown beside its button and retry clears the error", async () => {
  setup({ failOnce: true });
  const button = await screen.findByRole("button", { name: "一键游客体验" });
  fireEvent.click(button);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "游客创建过于频繁",
  );
  expect(button).toBeEnabled();
  fireEvent.click(button);
  expect(
    await screen.findByRole("heading", { name: "新建分析", level: 1 }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("closed guest access still offers ordinary login", async () => {
  setup({ enabled: false });
  expect(
    await screen.findByRole("heading", { name: "登录文镜" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "一键游客体验" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "登录" })).toBeEnabled();
});

test("exhausted guest allowance is visible and prevents new analysis", async () => {
  const fetch = setup({ initialGuest: true, remaining: 0 });
  expect(
    await screen.findByRole("heading", { name: "新建分析", level: 1 }),
  ).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByLabelText("游客空间与额度")).toHaveTextContent(
      "今日剩余 0 / 10 次分析",
    ),
  );
  expect(screen.getByRole("button", { name: "开始分析" })).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("08:00 重置");
  expect(fetch.mock.calls.some(([path]) => path === "/api/analyses")).toBe(
    false,
  );
});

test("a guest can sign into a regular account and leave the guest workspace", async () => {
  setup({ initialGuest: true });
  fireEvent.click(await screen.findByRole("link", { name: "登录正式账号" }));
  expect(
    await screen.findByRole("button", { name: "返回游客空间" }),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("邮箱"), {
    target: { value: regular.email },
  });
  fireEvent.change(screen.getByLabelText("密码", { exact: true }), {
    target: { value: "test-password-123" },
  });
  fireEvent.click(screen.getByRole("button", { name: "登录" }));
  expect(
    await screen.findByRole("heading", { name: "把文献读在一起。" }),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("游客空间与额度")).not.toBeInTheDocument();
  expect(screen.getByText(regular.email)).toBeInTheDocument();
});
