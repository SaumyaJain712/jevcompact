import { expect, test } from "@playwright/test";
import { MAIN } from "./helpers";

const SECRET = "sk-e2e-secret-key-7777";

test.describe("Settings screen", () => {
  test.afterEach(async ({ request }) => {
    await request.put(`${MAIN}/api/settings`, { data: { jev_api_key: "", cf_api_token: "", cf_account_id: "" } });
    await request.post(`${MAIN}/api/settings/reset`);
  });

  test("inline validation: keep must be higher than drop; Save disabled until valid", async ({ page }) => {
    await page.goto("/settings");
    const save = page.getByRole("button", { name: "Save changes" });
    await expect(save).toBeEnabled();
    await page.getByLabel("Keep threshold").fill("0.05");
    await expect(page.getByText("Keep threshold must be higher than drop threshold.")).toBeVisible();
    await expect(save).toBeDisabled();
    await page.getByLabel("Keep threshold").fill("0.60");
    await expect(save).toBeEnabled();
    await page.getByLabel("Token budget").fill("0");
    await expect(page.getByText("Enter a whole number of tokens above 0.")).toBeVisible();
    await expect(save).toBeDisabled();
  });

  test("toggles: fallback switch and locked 'never drop errors'", async ({ page }) => {
    await page.goto("/settings");
    const locked = page.getByRole("switch", { name: "Never drop error output (always on)" });
    await expect(locked).toBeDisabled();
    await expect(locked).toHaveAttribute("aria-checked", "true");
    const fb = page.getByRole("switch", { name: "Fall back to the plain summary if Jev fails" });
    await expect(fb).toHaveAttribute("aria-checked", "true");
    await fb.click();
    await expect(fb).toHaveAttribute("aria-checked", "false");
    await page.getByRole("button", { name: "Save changes" }).click();
    await page.reload();
    await expect(page.getByRole("switch", { name: "Fall back to the plain summary if Jev fails" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  test("API key is masked, Show reveals typed text, never shown in full after saving", async ({ page, request }) => {
    await page.goto("/settings");
    const key = page.getByLabel("API key", { exact: true });
    await key.fill(SECRET);
    await expect(key).toHaveAttribute("type", "password");
    await page.getByRole("button", { name: "Show" }).first().click();
    await expect(key).toHaveAttribute("type", "text");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Settings saved.")).toBeVisible();
    await page.reload();
    await expect(key).toHaveValue("");
    await expect(key).toHaveAttribute("placeholder", "••••••••7777");
    expect(await page.content()).not.toContain(SECRET);
    expect(await (await request.get(`${MAIN}/api/settings`)).text()).not.toContain(SECRET);
  });

  test("Test connection shows ✓ Connected or the error", async ({ page }) => {
    await page.goto("/settings");
    await page.getByRole("button", { name: "Test connection" }).first().click();
    await expect(page.getByText("✗ No Jev API key saved.")).toBeVisible();
    await page.route("**/api/settings/test/jev", (r) => r.fulfill({ json: { ok: true, message: "Connected" } }));
    await page.route("**/api/settings/test/cloudflare", (r) => r.fulfill({ json: { ok: true, message: "Connected" } }));
    await page.getByRole("button", { name: "Test connection" }).first().click();
    await page.getByRole("button", { name: "Test connection" }).nth(1).click();
    await expect(page.getByText("✓ Connected")).toHaveCount(2);
  });

  test("Reset to defaults", async ({ page }) => {
    await page.goto("/settings");
    await page.getByLabel("Token budget").fill("50000");
    await page.getByRole("button", { name: "Save changes" }).click();
    await page.getByRole("button", { name: "Reset to defaults" }).click();
    await expect(page.getByLabel("Token budget")).toHaveValue("120000");
    await expect(page.getByLabel("Keep threshold")).toHaveValue("0.50");
    await expect(page.getByLabel("Drop threshold")).toHaveValue("0.10");
  });
});
