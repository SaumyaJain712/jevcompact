import { expect, test } from "@playwright/test";
import { decisions, upload } from "./helpers";

test("TC-10 a score shows for every item", async ({ page, request }) => {
  const s = await upload(request, "checkout-bugfix-0412", { as: "tc10-checkout" });
  const ds = await decisions(request, s.run_id!);
  await page.goto(`/sessions/${s.id}`);
  const chips = page.getByTestId("action-chip");
  await expect(chips).toHaveCount(ds.length);
  const texts = await chips.allInnerTexts();
  texts.forEach((t, i) => {
    expect(t).toMatch(/^(Pinned|(Kept|Cut|Dropped) \d\.\d\d)$/);
    const d = ds[i];
    if (d.action === "Pinned") expect(t).toBe("Pinned");
    else expect(t).toBe(`${d.action} ${d.score!.toFixed(2)}`);
  });
  expect(texts.filter((t) => t !== "Pinned").length).toBeGreaterThan(0);
});
