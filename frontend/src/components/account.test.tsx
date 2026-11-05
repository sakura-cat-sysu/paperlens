import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import type { ReactNode } from "react";
import { AuthProvider } from "../auth";
import { App } from "../app";
import { AccountPage } from "./account";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function show(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>{ui}</AuthProvider>
    </QueryClientProvider>,
  );
}

const personal = {
  id: "c1",
  scope: "personal",
  name: "主账号",
  configured: true,
  api_key_hint: "sk-…1234",
  base_url: "https://api.deepseek.com",
  model: "deepseek-flash",
  protocol: "chat",
  updated_at: null,
};

const globalConfig = {
  id: "g1",
  scope: "global",
  name: "团队共用",
  configured: true,
  api_key_hint: "sk-…9999",
  base_url: "https://api.deepseek.com",
  model: "deepseek-chat",
  protocol: "chat",
  updated_at: null,
};

function payload(admin: boolean, models = [personal]) {
  return {
    user: { id: "u1", email: "test@example.com", is_admin: admin },
    created_at: "2026-11-01T00:00:00Z",
    usage: { used: 3, limit: 20, remaining: 17 },
    models,
    global_models: [globalConfig],
    environment_configured: true,
    default_model: "deepseek-flash",
    default_base_url: "https://api.deepseek.com",
    default_protocol: "chat",
  };
}

function stub({ admin = false, models = [personal] } = {}) {
  const calls: { url: string; method: string; body: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = String(input);
      const method = options?.method ?? "GET";
      calls.push({ url, method, body: String(options?.body ?? "") });
      if (url === "/api/auth/me")
        return json({
          user: { id: "u1", email: "test@example.com", is_admin: admin },
          csrf_token: "csrf",
        });
      if (url === "/api/account" && method === "GET")
        return json(payload(admin, models));
      if (url === "/api/account/models" && method === "POST")
        return json({ ...personal, id: "c2", name: "新配置" }, 201);
      if (url === "/api/account/models/c1" && method === "PUT")
        return json({ ...personal, model: "deepseek-chat" });
      if (url === "/api/account/models/c1" && method === "DELETE")
        return new Response(null, { status: 204 });
      if (url === "/api/account/password" && method === "POST")
        return new Response(null, { status: 204 });
      if (url === "/api/admin/models" && method === "POST")
        return json({ ...globalConfig, id: "g2" }, 201);
      return json({}, 404);
    }),
  );
  return calls;
}

test("shows account status and the saved personal configs", async () => {
  stub();
  show(<AccountPage />);
  expect(await screen.findByText("test@example.com")).toBeInTheDocument();
  expect(screen.getByText("今日分析")).toBeInTheDocument();
  expect(screen.getByText("主账号")).toBeInTheDocument();
});

test("the add form opens in a dialog", async () => {
  stub();
  show(<AccountPage />);
  await screen.findByText("主账号");
  expect(screen.queryByLabelText("API Key")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "添加配置" }));
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(screen.getByLabelText("API Key")).toBeInTheDocument();
  expect(screen.getByLabelText("配置备注")).toBeInTheDocument();
});

test("the model name and address start empty", async () => {
  stub();
  show(<AccountPage />);
  fireEvent.click(await screen.findByRole("button", { name: "添加配置" }));
  expect(await screen.findByLabelText("模型名称")).toHaveValue("");
  expect(screen.getByLabelText("API 根地址")).toHaveValue("");
});

test("a config without API Key is not submitted", async () => {
  const calls = stub();
  show(<AccountPage />);
  fireEvent.click(await screen.findByRole("button", { name: "添加配置" }));
  await screen.findByLabelText("API Key");
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  expect(await screen.findByText("请填写 API Key。")).toBeInTheDocument();
  expect(
    calls.some(
      (call) => call.method === "POST" && call.url === "/api/account/models",
    ),
  ).toBe(false);
});

test("adding a personal config posts it and closes the dialog", async () => {
  const calls = stub();
  show(<AccountPage />);
  fireEvent.click(await screen.findByRole("button", { name: "添加配置" }));
  const key = await screen.findByLabelText("API Key");
  fireEvent.change(key, { target: { value: "sk-new-1234" } });
  fireEvent.change(screen.getByLabelText("配置备注"), {
    target: { value: "备用账号" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  expect(await screen.findByText("个人配置已添加。")).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  const post = calls.find(
    (call) => call.url === "/api/account/models" && call.method === "POST",
  );
  expect(post?.body).toContain("sk-new-1234");
  expect(post?.body).toContain("备用账号");
});

test("the protocol defaults to chat and can be switched", async () => {
  const calls = stub();
  show(<AccountPage />);
  fireEvent.click(await screen.findByRole("button", { name: "添加配置" }));
  const protocol = await screen.findByLabelText("接口协议");
  expect(protocol).toHaveValue("chat");
  fireEvent.change(protocol, { target: { value: "messages" } });
  fireEvent.change(screen.getByLabelText("API Key"), {
    target: { value: "sk-ant-0001" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  expect(await screen.findByText("个人配置已添加。")).toBeInTheDocument();
  const post = calls.find(
    (call) => call.url === "/api/account/models" && call.method === "POST",
  );
  expect(post?.body).toContain('"protocol":"messages"');
});

test("editing an existing config sends a PUT with its id", async () => {
  const calls = stub();
  show(<AccountPage />);
  fireEvent.click(await screen.findByRole("button", { name: "编辑 主账号" }));
  const model = await screen.findByLabelText("模型名称");
  expect(model).toHaveValue("deepseek-flash");
  fireEvent.change(model, { target: { value: "deepseek-chat" } });
  fireEvent.click(screen.getByRole("button", { name: /保存修改/ }));
  expect(await screen.findByText("个人配置已更新。")).toBeInTheDocument();
  const put = calls.find((call) => call.method === "PUT");
  expect(put?.url).toBe("/api/account/models/c1");
  expect(put?.body).toContain("deepseek-chat");
});

test("changing the password happens in a dialog", async () => {
  const calls = stub();
  show(<AccountPage />);
  fireEvent.click(await screen.findByRole("button", { name: "修改密码" }));
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("当前密码"), {
    target: { value: "old-password-123" },
  });
  fireEvent.change(screen.getByLabelText("新密码"), {
    target: { value: "new-password-456" },
  });
  fireEvent.change(screen.getByLabelText("确认新密码"), {
    target: { value: "new-password-456" },
  });
  fireEvent.click(screen.getByRole("button", { name: "更新密码" }));
  expect(
    await screen.findByText(/密码已更新，其他设备上的登录已失效/),
  ).toBeInTheDocument();
  const post = calls.find((call) => call.url === "/api/account/password");
  expect(post?.body).toContain("new-password-456");
});

test("without any config it only explains, without action buttons", async () => {
  stub({ models: [] });
  show(<AccountPage />);
  expect(await screen.findByText("还没有可用的模型配置")).toBeInTheDocument();
  expect(screen.getByText(/可以等管理员配置好全局模型/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "我自己配置" }),
  ).not.toBeInTheDocument();
  // 右上角的添加入口仍然保留。
  expect(screen.getByRole("button", { name: "添加配置" })).toBeInTheDocument();
});

test("only administrators see the global configs", async () => {
  stub({ admin: false });
  show(<AccountPage />);
  await screen.findByText("主账号");
  expect(screen.queryByText(/全局模型配置/)).not.toBeInTheDocument();

  cleanup();
  stub({ admin: true });
  show(<AccountPage />);
  await waitFor(() =>
    expect(screen.getByText(/全局模型配置/)).toBeInTheDocument(),
  );
  expect(screen.getByText("团队共用")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "添加全局配置" }),
  ).toBeInTheDocument();
});

test("/account 进入账号设置页，而不是 404 回退", async () => {
  window.history.pushState({}, "", "/account");
  stub();
  show(<App />);
  expect(
    await screen.findByRole("heading", { name: "账号设置" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("页面不存在")).not.toBeInTheDocument();
  expect(await screen.findByText("账号状态")).toBeInTheDocument();
});
