import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { ReportView } from "./report";
import type { Report } from "../api/client";

afterEach(cleanup);
const finding = {
  text: "只在研究范围内观察到效率改善。",
  claim_ids: ["D1-C1"],
  basis: "inference",
};
const report: Report = {
  question: "研究问题",
  model: "test-model",
  generated_at: "2026-11-02",
  documents: [
    {
      document_id: "D1",
      filename: "文献.pdf",
      sha256: "abc",
      size_bytes: 100,
      pages: [
        {
          number: 1,
          text: "Original evidence in its context.",
          paragraphs: [],
        },
      ],
      warnings: [],
    },
  ],
  analyses: [
    {
      document_id: "D1",
      filename: "文献.pdf",
      claims: [
        {
          claim_id: "D1-C1",
          document_id: "D1",
          claim: "文献报告效率改善。",
          explanation: "限于实验设定",
          evidence: [
            {
              document_id: "D1",
              page: 1,
              quote: "Original evidence",
              verified: true,
              reason: "",
            },
          ],
        },
      ],
      gaps: ["长期效果未知"],
      warnings: [],
    },
  ],
  tasks: [{ task_id: "Q1", title: "直接回答", kind: "evidence" }],
  comparison: {
    summary: finding,
    answers: [
      {
        task_id: "Q1",
        status: "answered",
        statements: [finding],
        limitations: "",
        caveats: "不能推广到所有人群。",
      },
    ],
    agreements: [],
    disagreements: [],
    method_differences: [],
    reasons: [],
    unresolved_questions: ["长期效果如何？"],
    warnings: [],
  },
};

test("draft status, evidence dialog, page context and section navigation", () => {
  render(<ReportView report={report} complete={false} />);
  expect(screen.getByText("报告草稿 · 1/1 项已回答")).toBeInTheDocument();
  fireEvent.click(
    screen.getAllByRole("button", { name: "查看 D1-C1 的原文证据" })[0],
  );
  expect(screen.getByRole("dialog")).toHaveTextContent("Original evidence");
  fireEvent.click(screen.getByRole("button", { name: /查看整页正文/ }));
  expect(
    screen.getByText("Original evidence in its context."),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "关闭" }));
  fireEvent.click(screen.getByRole("button", { name: "待研究问题" }));
  expect(screen.getByText("长期效果如何？")).toBeInTheDocument();
});

test("unverified claim stays marked for review and text cannot execute HTML", () => {
  const value = structuredClone(report);
  value.analyses[0].claims[0].evidence[0].verified = false;
  value.analyses[0].claims[0].claim = "<img src=x onerror=alert(1)>";
  render(<ReportView report={value} complete />);
  fireEvent.click(screen.getByRole("button", { name: "文献观点" }));
  expect(screen.getByText("待复核 · 未参与综合")).toBeInTheDocument();
  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
  expect(document.querySelector("img")).toBeNull();
});
