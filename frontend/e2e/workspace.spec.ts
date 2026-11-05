import { expect, test } from "@playwright/test";
import path from "node:path";

const password = "browser-test-password-123";
const inviteCode = "E2EBROWSERTESTAB";

test("real upload → queued worker → evidence report → refresh and mobile", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/login");
  await page.getByRole("button", { name: "还没有账号？创建账号" }).click();
  await page.getByLabel("邮箱").fill(`browser-${Date.now()}@example.com`);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByLabel("邀请码").fill(inviteCode);
  await page.getByRole("button", { name: "创建账号并登录" }).click();
  await expect(
    page.getByRole("heading", { name: "把文献读在一起。" }),
  ).toBeVisible();
  await page.screenshot({
    path: "../artifacts/ui-review/workspace-desktop.png",
    fullPage: true,
  });
  await page
    .getByRole("link", { name: "新建分析", exact: true })
    .first()
    .click();
  await page
    .getByLabel("上传 PDF 文献")
    .setInputFiles([
      path.resolve("../.cache/e2e/paper-1.pdf"),
      path.resolve("../.cache/e2e/paper-2.pdf"),
    ]);
  await expect(page.getByRole("checkbox")).toHaveCount(2);
  await page.getByRole("checkbox").nth(0).check();
  await page.getByRole("checkbox").nth(1).check();
  await page
    .getByLabel("你想从这些文献中了解什么？")
    .fill("比较这些文献的效率结果。");
  await page.setViewportSize({ width: 375, height: 900 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../artifacts/ui-review/new-analysis-375.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "开始分析" }).click();
  await expect(page).toHaveURL(/\/analyses\//);
  await expect(page.getByText("1/1 项回答已生成", { exact: true })).toBeVisible(
    { timeout: 30000 },
  );
  const reportUrl = page.url();
  await page.reload();
  await expect(
    page.getByText("1/1 项回答已生成", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "查看 D1-C1 的原文证据" })
    .first()
    .click();
  await expect(page.getByRole("dialog")).toContainText("Synthetic study 2");
  await page.getByRole("button", { name: /查看整页正文/ }).click();
  await expect(page.getByText("第 1 页 · 提取正文")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "查看 D1-C1 的原文证据" }).first(),
  ).toBeFocused();
  await page.screenshot({
    path: "../artifacts/ui-review/report-desktop.png",
    fullPage: true,
  });
  for (const width of [320, 375, 768]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(
      page.getByRole("heading", { name: "比较这些文献的效率结果。" }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `../artifacts/ui-review/report-${width}.png`,
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 375, height: 900 });
  await page.getByRole("button", { name: "打开导航" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "打开导航" })).toBeFocused();
  await page.getByRole("button", { name: "打开导航" }).click();
  await page.getByRole("link", { name: "文献库", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "文献库", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../artifacts/ui-review/library-375.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByLabel("上传 PDF 文献").setInputFiles({
    name: "broken.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("invalid"),
  });
  await expect(page.getByRole("alert")).toBeVisible();
  await page.goto(reportUrl);
  await expect(
    page.getByText("1/1 项回答已生成", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "删除分析报告" }).click();
  await expect(page.getByRole("dialog")).toContainText("此操作无法撤销");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("login page fits narrow screens and supports keyboard submission", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "登录文镜" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByLabel("邮箱").fill("missing@example.com");
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByLabel("密码", { exact: true }).press("Enter");
  await expect(page.getByRole("alert")).toContainText("邮箱或密码不正确");
  await page.screenshot({
    path: "../artifacts/ui-review/login-320.png",
    fullPage: true,
  });
});

test("guest entry → analysis → logout and resume keeps the same files and quota", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto("/login");
  await expect(
    page.getByRole("button", { name: "一键游客体验" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../artifacts/ui-review/guest-entry-320.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "一键游客体验" }).click();
  await expect(page).toHaveURL(/\/new$/);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await expect(
    page.getByRole("complementary", { name: "游客空间与额度" }),
  ).toContainText("10 / 10");
  await page
    .getByLabel("上传 PDF 文献")
    .setInputFiles([
      path.resolve("../.cache/e2e/paper-1.pdf"),
      path.resolve("../.cache/e2e/paper-2.pdf"),
    ]);
  await expect(page.getByRole("checkbox")).toHaveCount(2);
  await page.getByRole("checkbox").nth(0).check();
  await page.getByRole("checkbox").nth(1).check();
  await page
    .getByLabel("你想从这些文献中了解什么？")
    .fill("比较这些文献的效率结果。");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "开始分析" }).click();
  await expect(page.getByText("1/1 项回答已生成", { exact: true })).toBeVisible(
    { timeout: 30000 },
  );
  await expect(
    page.getByRole("complementary", { name: "游客空间与额度" }),
  ).toContainText("9 / 10");
  await page.reload();
  await expect(
    page.getByText("1/1 项回答已生成", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "退出游客体验" }).click();
  await expect(
    page.getByRole("button", { name: "一键游客体验" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "一键游客体验" }).click();
  await expect(page.getByRole("checkbox")).toHaveCount(2);
  await expect(
    page.getByRole("complementary", { name: "游客空间与额度" }),
  ).toContainText("9 / 10");
  await page.screenshot({
    path: "../artifacts/ui-review/guest-resumed-desktop.png",
    fullPage: true,
  });
});
