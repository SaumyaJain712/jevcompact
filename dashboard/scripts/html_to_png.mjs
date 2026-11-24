// Render local HTML files to full-page PNGs next to them (used by scripts/db_snapshots.py).
//   node scripts/html_to_png.mjs a.html b.html
import { chromium } from "@playwright/test";
import { pathToFileURL } from "node:url";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1.5 });
for (const file of process.argv.slice(2)) {
  await page.goto(pathToFileURL(file).href);
  const box = await page.locator("body").boundingBox();
  await page.setViewportSize({ width: Math.max(1440, Math.ceil((box?.width ?? 1400) + 48)), height: 900 });
  await page.screenshot({ path: file.replace(/\.html$/, ".png"), fullPage: true });
}
await browser.close();
