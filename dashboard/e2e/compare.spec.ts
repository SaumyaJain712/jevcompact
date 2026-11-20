import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { MAIN, upload } from "./helpers";

test("Compare: same order, totals, markers, summary bar and exports", async ({ page, request }) => {
  const s = await upload(request, "checkout-bugfix-0412", { as: "compare-checkout" });
  const cmp = await (await request.get(`${MAIN}/api/runs/${s.run_id}/compare`)).json();
  await page.goto(`/sessions/${s.id}/compare`);

  const heads = page.locator(".col-head");
  await expect(heads.nth(0)).toContainText(`Before${cmp.tokens_before.toLocaleString("en-US")} tokens`);
  await expect(heads.nth(1)).toContainText(`After${cmp.tokens_after.toLocaleString("en-US")} tokens`);
  await expect(page.getByTestId("compare-row")).toHaveCount(cmp.rows.length);

  const bar = (await page.getByTestId("summary-bar").locator("span").allInnerTexts()).join(" ");
  expect(bar).toMatch(/^Jev cost \$\d\.\d{4} · \d+\.\d\d s · \d+ dropped · \d+ truncated · 0 user messages touched/);
  await expect(page.locator(".cell.after .chip", { hasText: "Dropped" }).first()).toBeVisible();
  await expect(page.locator(".cell.after .chip", { hasText: "Truncated" }).first()).toBeVisible();

  const [json] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Export JSON" }).click()]);
  const exported = JSON.parse(readFileSync((await json.path())!, "utf-8"));
  expect(exported).toEqual(await (await request.get(`${MAIN}/api/runs/${s.run_id}/export.json`)).json());
  expect(json.suggestedFilename()).toMatch(/compare-checkout-compacted-\d+\.json/);

  const [csv] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export report (CSV)" }).click(),
  ]);
  const lines = readFileSync((await csv.path())!, "utf-8").trim().split(/\r?\n/);
  expect(lines[0]).toBe("item_id,message_index,role,title,score,action,reason,tokens_before,tokens_after,summarized");
  expect(lines.at(-1)).toMatch(/^TOTAL/);
});
