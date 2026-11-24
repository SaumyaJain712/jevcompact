import { expect, test } from "@playwright/test";
import { decisions, MAIN, SLOW, upload } from "./helpers";

const HEADLINE = /^\d+k → \d+k tokens \(\d+% smaller\) · Jev cost \$\d\.\d{4} · \d+\.\d\d s$/;

test.describe("Session review screen", () => {
  test("header line, buttons, collapsed output", async ({ page, request }) => {
    const s = await upload(request, "checkout-bugfix-0412", { as: "review-basic" });
    await page.goto(`/sessions/${s.id}`);
    await expect(page.getByTestId("headline")).toHaveText(HEADLINE);
    for (const b of ["Undo", "Redo", "Compare"]) await expect(page.getByRole("button", { name: b, exact: true })).toBeVisible();
    const items = page.getByTestId("item");
    await expect(items.first().locator("pre")).toHaveCount(0);
    await items.nth(1).locator(".item-head").click();
    const ds = await decisions(request, s.run_id!);
    await expect(items.nth(1).locator("pre.output")).toHaveText(ds[1].content.trimEnd(), { useInnerText: false });
    await expect(items.nth(1).locator(".role")).toHaveText(/USER|TOOL|ERROR/);
  });

  test("J/K move, R restores, U undoes back to the original (version 0)", async ({ page, request }) => {
    const s = await upload(request, "checkout-bugfix-0412", { as: "review-keys" });
    const ds = await decisions(request, s.run_id!);
    const target = ds.findIndex((d) => d.action === "Dropped");
    expect(target).toBeGreaterThan(0);
    await page.goto(`/sessions/${s.id}`);
    const items = page.getByTestId("item");
    await expect(items.first()).toHaveClass(/selected/);
    await page.keyboard.press("j");
    await page.keyboard.press("j");
    await expect(items.nth(2)).toHaveClass(/selected/);
    await page.keyboard.press("k");
    await expect(items.nth(1)).toHaveClass(/selected/);
    await page.keyboard.press("k");
    for (let i = 0; i < target; i++) await page.keyboard.press("j");
    await expect(items.nth(target)).toHaveClass(/selected/);

    await page.keyboard.press("r");
    await expect(items.nth(target)).toContainText("Restored");
    await expect(items.nth(target).getByTestId("action-chip")).toHaveText("Restored");

    await page.keyboard.press("u");
    await expect(items.nth(target).getByTestId("action-chip")).toHaveText(/^Dropped/);
    await page.keyboard.press("u");
    await expect(page.locator(".page-header .chip")).toHaveText("Original");
    await expect(page.getByTestId("headline")).toContainText("(0% smaller) · original session, version 0");
    await expect(items.first().getByTestId("action-chip")).toHaveText("Original");
    await expect(page.getByRole("button", { name: "Undo", exact: true })).toBeDisabled();

    await page.getByRole("button", { name: "Redo", exact: true }).click();
    await expect(page.locator(".page-header .chip")).toHaveText(/Compacted|Fell back/);
  });

  test("dropped banner offers Undo and Restore one", async ({ page, request }) => {
    const s = await upload(request, "checkout-bugfix-0412", { as: "review-banner" });
    await page.goto(`/sessions/${s.id}`);
    const banner = page.getByRole("alert").filter({ hasText: "dropped" });
    await expect(banner).toHaveText(/\d+ items? dropped\. ".+" was among them\./);
    await expect(banner.getByRole("button", { name: "Undo" })).toBeVisible();
    await banner.getByRole("button", { name: "Restore one" }).click();
    await expect(page.getByTestId("action-chip").filter({ hasText: /^Restored$/ })).toHaveCount(1);
    await expect(page.getByRole("alert").filter({ hasText: "dropped" })).toHaveCount(0);
  });

  test("Re-run with a preset and threshold validation", async ({ page, request }) => {
    const s = await upload(request, "checkout-bugfix-0412", { as: "review-rerun" });
    await page.goto(`/sessions/${s.id}`);
    await page.getByLabel("Preset").selectOption("aggressive");
    await expect(page.locator("output[for=keep]")).toHaveText("0.70");
    await expect(page.locator("output[for=drop]")).toHaveText("0.20");
    await page.getByRole("button", { name: "Re-run" }).click();
    const session = async () => (await request.get(`${MAIN}/api/sessions/${s.id}`)).json();
    await expect.poll(async () => (await session()).version, { timeout: 60_000 }).toBe(2);
    const d = await session();
    expect([d.current_run.keep_threshold, d.current_run.drop_threshold]).toEqual([0.7, 0.2]);
    await expect(page.getByRole("button", { name: "Re-run" })).toBeEnabled({ timeout: 60_000 });
    await expect(page.locator("output[for=keep]")).toHaveText("0.70");

    await page.locator("#keep").fill("0.05");
    await expect(page.getByText("Keep threshold must be higher than drop threshold.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Re-run" })).toBeDisabled();
    await expect(page.getByLabel("Preset")).toHaveValue("custom");
  });

  test("items folded into the summary can be restored", async ({ page, request }) => {
    const s = await upload(request, "checkout-bugfix-0412", { as: "review-folded" });
    await request.post(`${MAIN}/api/sessions/${s.id}/runs?wait=true`, { data: { budget: 5000 }, timeout: 60_000 });
    await page.goto(`/sessions/${s.id}`);
    const folded = page.getByTestId("item").filter({ hasText: "In summary" }).first();
    await expect(folded).toBeVisible();
    const title = await folded.locator(".item-title .mono").innerText();
    await folded.getByRole("button", { name: "Restore", exact: true }).click();
    const back = page.getByTestId("item").filter({ hasText: title }).filter({ hasText: "Restored" });
    await expect(back.first()).toBeVisible();
  });

  test("Jev timeout banner (real 5 s timeout) with Retry and View log", async ({ page, request }) => {
    test.setTimeout(120_000);
    const s = await upload(request, "checkout-bugfix-0412", { as: "review-timeout", base: SLOW });
    expect(s.status).toBe("Fell back");
    await page.goto(`${SLOW}/sessions/${s.id}`);
    const banner = page.getByRole("alert").filter({ hasText: "Fell back" });
    await expect(banner).toContainText("Jev didn't respond in 5 s. We used the plain summary instead, so nothing was lost.");
    await expect(banner.getByRole("button", { name: "Retry with Jev" })).toBeVisible();
    await expect(page.getByTestId("item").first()).toBeVisible({ timeout: 30_000 });
    for (const chip of await page.getByTestId("action-chip").allInnerTexts()) expect(chip).toMatch(/^(Pinned|Kept)$/);
    await banner.getByRole("button", { name: "View log" }).click();
    await expect(page.getByRole("heading", { name: "Decision log" })).toBeVisible();
    await expect(page.getByText(/Fallback reason: Jev didn't respond in 5 s/)).toBeVisible();
  });
});
