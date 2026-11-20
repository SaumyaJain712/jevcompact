import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { ROOT, SAMPLE_NAMES, SLOW, upload } from "./helpers";

// Run with `npm run screenshots`. Writes docs/screenshots/*.png at 1440×900 from a clean server.
const SHOTS = "http://127.0.0.1:8792";
const OUT = path.join(ROOT, "docs", "screenshots");
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`) });

test("@screenshots all screens, banners and the validation error", async ({ page, request }) => {
  test.setTimeout(240_000);
  const ids: Record<string, string> = {};
  for (const name of [...SAMPLE_NAMES].reverse()) ids[name] = (await upload(request, name, { base: SHOTS })).id;
  const checkout = ids["checkout-bugfix-0412"];

  await page.goto(`${SHOTS}/sessions`);
  await expect(page.locator("tbody tr")).toHaveCount(SAMPLE_NAMES.length);
  await shot(page, "01-sessions");

  await page.goto(`${SHOTS}/sessions/${checkout}`);
  await expect(page.getByTestId("item").first()).toBeVisible();
  for (let i = 0; i < 3; i++) await page.keyboard.press("j");
  await page.getByTestId("item").nth(3).locator(".item-head").click();
  await shot(page, "02-review");
  await page.getByTestId("item").nth(3).locator(".item-head").click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, "07-banner-items-dropped");

  await page.goto(`${SHOTS}/sessions/${checkout}/compare`);
  await expect(page.getByTestId("compare-row").first()).toBeVisible();
  await shot(page, "03-compare");

  await page.goto(`${SHOTS}/settings`);
  await expect(page.getByLabel("Token budget")).toBeVisible();
  await shot(page, "04-settings");
  await page.getByLabel("Keep threshold").fill("0.05");
  await expect(page.getByText("Keep threshold must be higher than drop threshold.")).toBeVisible();
  await shot(page, "08-settings-validation-error");

  await page.goto(`${SHOTS}/sessions`);
  await expect(page.locator("tbody tr")).toHaveCount(SAMPLE_NAMES.length);
  await page.getByTestId("file-input").setInputFiles({ name: "notes.json", mimeType: "application/json", buffer: Buffer.from("{}") });
  await expect(page.getByRole("alert")).toBeVisible();
  await shot(page, "06-banner-upload-error");

  const slow = await upload(request, "checkout-bugfix-0412", { base: SLOW });
  await page.goto(`${SLOW}/sessions/${slow.id}`);
  await expect(page.getByRole("alert").filter({ hasText: "didn't respond" })).toBeVisible();
  await expect(page.getByTestId("item").first()).toBeVisible({ timeout: 30_000 });
  await shot(page, "05-banner-jev-timeout");
});
