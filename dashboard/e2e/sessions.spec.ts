import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { SAMPLE_NAMES, sessionFile, upload } from "./helpers";

const UPLOAD_ERROR = "This file isn't a message list. We expected a JSON array of {role, content}.";

test.describe("Sessions screen", () => {
  test.beforeAll(async ({ request }) => {
    for (const name of SAMPLE_NAMES) await upload(request, name);
  });

  test("table shows sessions, messages, tokens and status words", async ({ page }) => {
    await page.goto("/sessions");
    await expect(page.getByRole("heading", { name: "Sessions" })).toBeVisible();
    const row = page.getByRole("row", { name: /checkout-bugfix-0412/ }).first();
    await expect(row).toContainText(/\d+k → \d+k/);
    await expect(row.locator(".chip")).toHaveText(/Compacted|Fell back|Under budget/);
    const docs = page.getByRole("row", { name: /docs-migration/ }).first();
    await expect(docs.locator(".chip")).toHaveText("Under budget");
  });

  test("search and filter chips", async ({ page }) => {
    await page.goto("/sessions");
    await page.getByLabel("Search sessions").fill("checkout");
    await expect(page.locator("tbody tr")).not.toHaveCount(0);
    for (const r of await page.locator("tbody tr").allInnerTexts()) expect(r).toContain("checkout");
    await page.getByLabel("Search sessions").fill("");
    for (const f of ["Compacted", "Fell back"]) {
      await page.getByRole("button", { name: f, exact: true }).click();
      await expect(page.getByRole("button", { name: f, exact: true })).toHaveAttribute("aria-pressed", "true");
      await page.waitForTimeout(400);
      for (const chip of await page.locator("tbody .chip").allInnerTexts()) expect(chip).toBe(f);
    }
    await page.getByRole("button", { name: "All", exact: true }).click();
    await expect(page.locator("tbody tr")).toHaveCount(await page.locator("tbody tr").count());
  });

  test("upload button sends a valid file and opens its review", async ({ page }) => {
    await page.goto("/sessions");
    await page.getByTestId("file-input").setInputFiles(sessionFile("docs-migration"));
    await expect(page).toHaveURL(/\/sessions\/[0-9a-f]+$/);
    await expect(page.getByTestId("headline")).toBeVisible();
  });

  test("invalid file shows the banner with one recovery button", async ({ page }) => {
    await page.goto("/sessions");
    await page.getByTestId("file-input").setInputFiles({
      name: "notes.json",
      mimeType: "application/json",
      buffer: Buffer.from('{"not": "a list"}'),
    });
    const banner = page.getByRole("alert");
    await expect(banner).toContainText(UPLOAD_ERROR);
    const chooser = page.waitForEvent("filechooser");
    await banner.getByRole("button", { name: "Choose another file" }).click();
    await chooser;
  });

  test("non-.json files are rejected before upload", async ({ page }) => {
    let uploads = 0;
    page.on("request", (r) => r.method() === "POST" && r.url().includes("/api/sessions") && uploads++);
    await page.goto("/sessions");
    await page.getByTestId("file-input").setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("[]") });
    await expect(page.getByRole("alert")).toContainText(UPLOAD_ERROR);
    expect(uploads).toBe(0);
  });

  test("drag and drop accepts .json and validates it", async ({ page }) => {
    await page.goto("/sessions");
    const drop = async (name: string, text: string) => {
      const dt = await page.evaluateHandle(
        ({ name, text }) => {
          const d = new DataTransfer();
          d.items.add(new File([text], name, { type: "application/json" }));
          return d;
        },
        { name, text },
      );
      await page.dispatchEvent("[data-testid=dropzone]", "drop", { dataTransfer: dt });
    };
    await drop("bad.json", "[1, 2, 3]");
    await expect(page.getByRole("alert")).toContainText(UPLOAD_ERROR);
    await drop("docs-migration.json", readFileSync(sessionFile("docs-migration"), "utf-8"));
    await expect(page).toHaveURL(/\/sessions\/[0-9a-f]+$/);
  });
});
