import { expect, test } from "@playwright/test";

test("中文工作台展示原生流程和时间线", async ({ page }) => {
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));

  await page.goto("/");

  await expect(page.getByText("NARRASCAPE", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "制作流程" })).toBeVisible();
  await expect(page.getByRole("button", { name: "制作流程" })).toBeVisible();
  await expect(page.getByText("导演契约", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "时间线" }).click();
  await expect(page.getByRole("heading", { name: "影片时间线", level: 1 })).toBeVisible();
  await expect(page.getByText("画面", { exact: true })).toBeVisible();

  expect(browserErrors).toEqual([]);
});
