import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import type { ReactNode } from "react";
import { Invites } from "./invites";

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
test("a successful revoke retry clears the old failure message", async () => {
  let attempts = 0;
  let revoked = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, options?: RequestInit) => {
      const invite = {
        id: "invite-1",
        code_hint: "AB****CD",
        note: "Review fixture",
        grants_admin: false,
        max_uses: 1,
        used_count: 0,
        state: revoked ? "revoked" : "active",
        expires_at: null,
        created_at: "2026-11-03T00:00:00Z",
      };
      if (options?.method === "POST") {
        attempts += 1;
        if (attempts === 1)
          return json({ detail: "暂时无法吊销，请重试。" }, 503);
        revoked = true;
        return json({ ...invite, state: "revoked" });
      }
      return json([invite]);
    }),
  );
  show(<Invites />);
  const revoke = await screen.findByRole("button", {
    name: "吊销邀请码 AB****CD",
  });
  fireEvent.click(revoke);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "暂时无法吊销，请重试。",
  );
  await waitFor(() => expect(revoke).toBeEnabled());
  fireEvent.click(revoke);
  await screen.findByText("已吊销");
  expect(attempts).toBe(2);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
