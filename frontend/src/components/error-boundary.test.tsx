import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ErrorBoundary } from "./error-boundary";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function Boom(): never {
  throw new Error("测试用的渲染错误");
}

test("shows a readable message instead of a blank page", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  render(
    <ErrorBoundary compact>
      <Boom />
    </ErrorBoundary>,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("页面出错了");
  expect(screen.getByText("测试用的渲染错误")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /重试/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /刷新页面/ })).toBeInTheDocument();
});

test("retry re-renders the children", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  let broken = true;
  function Flaky() {
    if (broken) throw new Error("boom");
    return <p>已经恢复</p>;
  }
  render(
    <ErrorBoundary>
      <Flaky />
    </ErrorBoundary>,
  );
  expect(screen.getByRole("alert")).toBeInTheDocument();
  broken = false;
  fireEvent.click(screen.getByRole("button", { name: /重试/ }));
  expect(screen.getByText("已经恢复")).toBeInTheDocument();
});
