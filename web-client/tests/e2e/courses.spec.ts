import { test, expect } from "@playwright/test";

test.describe("Course browse page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/courses");
  });

  test("renders the page heading", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /browse courses/i })).toBeVisible();
  });

  test("search input is visible", async ({ page }) => {
    await expect(page.getByPlaceholder(/search courses/i)).toBeVisible();
  });

  test("typing in search updates the URL", async ({ page }) => {
    await page.getByPlaceholder(/search courses/i).fill("python");
    await page.waitForURL(/search=python/, { timeout: 2000 });
    expect(page.url()).toContain("search=python");
  });
});
