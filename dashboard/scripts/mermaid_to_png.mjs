// Render Mermaid diagrams (.mmd) to PNG next to them. Needs network once for mermaid from jsDelivr.
//   node scripts/mermaid_to_png.mjs ../docs/diagrams/*.mmd
import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 2 });
for (const file of process.argv.slice(2)) {
  const src = readFileSync(file, "utf-8");
  await page.setContent(`<!doctype html><html><body style="margin:0;background:#fff">
    <pre class="mermaid">${src.replace(/</g, "&lt;")}</pre>
    <script type="module">
      import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.esm.min.mjs";
      mermaid.initialize({ startOnLoad: false, theme: "neutral", fontFamily: "Inter, system-ui, sans-serif",
                           flowchart: { htmlLabels: true }, er: { useMaxWidth: false } });
      await mermaid.run({ querySelector: ".mermaid" });
      document.body.dataset.done = "1";
    </script></body></html>`);
  await page.waitForSelector("body[data-done='1']", { timeout: 30_000 });
  await page.locator(".mermaid svg").screenshot({ path: file.replace(/\.mmd$/, ".png") });
  console.log("wrote", file.replace(/\.mmd$/, ".png"));
}
await browser.close();
