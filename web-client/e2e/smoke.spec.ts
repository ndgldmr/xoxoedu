import {expect, test} from "@playwright/test";

test("app entry routes and protected redirects follow the subdomain contract", async ({
  page,
}) => {
  await page.goto("/sign-in");
  await expect(page).toHaveURL(/\/sign-in$/);
  await expect(page.getByRole("heading", {name: /sign into xoxo education/i})).toBeVisible();

  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/sign-in\?next=%2Fdashboard$/);

  await page.goto("/admin");
  await expect(page).toHaveURL(/\/sign-in\?next=%2Fadmin$/);
});
