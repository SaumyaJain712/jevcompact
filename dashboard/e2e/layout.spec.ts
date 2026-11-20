import { expect, test, type Page } from "@playwright/test";
import { contrastFailures, upload } from "./helpers";

let sid = "";
test.beforeAll(async ({ request }) => {
  sid = (await upload(request, "checkout-bugfix-0412", { as: "layout-checkout" })).id;
});

const screens = () => [
  ["Sessions", "/sessions", "Upload session"],
  ["Review", `/sessions/${sid}`, "Compare"],
  ["Compare", `/sessions/${sid}/compare`, "Export JSON"],
  ["Settings", "/settings", "Save changes"],
];

async function ready(page: Page) {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("h1")).toBeVisible();
}

test("sidebar and one primary button, top right, on every screen", async ({ page }) => {
  for (const [name, path, primary] of screens()) {
    await page.goto(path);
    await ready(page);
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(page.getByRole("link", { name: "JevCompact home" })).toBeVisible();
    for (const item of ["Sessions", "Review", "Compare", "Settings"]) await expect(nav.getByText(item, { exact: true })).toBeVisible();
    await expect(nav.locator(".active")).toHaveText(name);
    const primaries = page.locator(".btn-primary");
    await expect(primaries).toHaveCount(1);
    await expect(primaries).toHaveText(primary);
    const box = (await primaries.boundingBox())!;
    const header = (await page.locator(".page-header").boundingBox())!;
    expect(Math.abs(box.x + box.width - (header.x + header.width))).toBeLessThan(2); // right edge
    expect(box.y - header.y).toBeLessThan(8); // top
  }
});

test("style guide: colours, fonts, ≥ 4.5:1 contrast, status words", async ({ page }) => {
  await page.goto("/sessions");
  await ready(page);
  const vars = await page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement);
    return ["--navy", "--red", "--green", "--amber", "--grey", "--bg"].map((v) => cs.getPropertyValue(v).trim().toUpperCase());
  });
  expect(vars).toEqual(["#293786", "#A21D2E", "#1E6B45", "#8A5A00", "#5B6573", "#F7F8FC"]);
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe("rgb(247, 248, 252)");
  const h1 = await page.locator("h1").evaluate((e) => [getComputedStyle(e).fontFamily, getComputedStyle(e).fontSize]);
  expect(h1[0]).toContain("Inter");
  expect(h1[1]).toBe("24px");
  expect(await page.evaluate(() => getComputedStyle(document.body).fontSize)).toBe("14px");
  expect(await page.evaluate(() => document.fonts.check('14px "Inter"'))).toBe(true);

  await page.goto(`/sessions/${sid}`);
  await ready(page);
  await page.getByTestId("item").nth(1).locator(".item-head").click();
  const mono = await page.locator("pre.output").evaluate((e) => [getComputedStyle(e).fontFamily, getComputedStyle(e).fontSize]);
  expect(mono[0]).toContain("JetBrains Mono");
  expect(mono[1]).toBe("13px");

  const TEXT = ".chip, .role, .btn, .banner .msg, .nav a, h1, h2, .sub, td, th, label, .hint, .tokens, .keys, .item-title, .tag, output";
  for (const [, path] of screens()) {
    await page.goto(path);
    await ready(page);
    expect(await contrastFailures(page, TEXT), path).toEqual([]);
    for (const chip of await page.locator(".chip").allInnerTexts()) expect(chip.trim().length, "status word").toBeGreaterThan(0);
  }
});
