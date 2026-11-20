import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
export const SAMPLES_DIR = path.join(ROOT, "data", "samples");
export const PREVIEW_DIR = path.join(ROOT, ".e2e-data", "preview-sessions");
export const SAMPLE_NAMES = ["checkout-bugfix-0412", "api-refactor-long", "data-pipeline-test", "docs-migration"];
export const MAIN = "http://127.0.0.1:8790";
export const SLOW = "http://127.0.0.1:8791";

export function sessionFile(name: string): string {
  const real = path.join(SAMPLES_DIR, `${name}.json`);
  return existsSync(real) ? real : path.join(PREVIEW_DIR, `${name}.json`);
}

export function sessionJson(name: string): unknown[] {
  return JSON.parse(readFileSync(sessionFile(name), "utf-8"));
}

export interface Uploaded {
  id: string;
  name: string;
  status: string | null;
  tokens_before: number;
  tokens_after: number | null;
  run_id: string | null;
}

/** Upload a session through the API and wait for its compaction to finish. */
export async function upload(request: APIRequestContext, sample: string, opts: { as?: string; base?: string } = {}) {
  const base = opts.base ?? MAIN;
  const res = await request.post(`${base}/api/sessions?wait=true&name=${encodeURIComponent(opts.as ?? sample)}`, {
    data: sessionJson(sample),
    timeout: 60_000,
  });
  expect(res.status(), await res.text()).toBe(201);
  return (await res.json()) as Uploaded;
}

export async function decisions(request: APIRequestContext, runId: string, base = MAIN) {
  return (await (await request.get(`${base}/api/runs/${runId}/decisions`)).json()) as {
    item_id: string;
    title: string;
    action: string;
    score: number | null;
    summarized: boolean;
    content: string;
  }[];
}

/** WCAG contrast ratio of every text element matching `selector` against its effective background. */
export async function contrastFailures(page: Page, selector: string): Promise<string[]> {
  return page.evaluate((sel) => {
    const parse = (c: string) => (c.match(/[\d.]+/g) || []).map(Number);
    const lum = ([r, g, b]: number[]) => {
      const f = (v: number) => {
        v /= 255;
        return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    const bgOf = (el: Element | null): number[] => {
      while (el) {
        const c = parse(getComputedStyle(el).backgroundColor);
        if (c.length >= 3 && (c.length < 4 || c[3] > 0.5)) return c.slice(0, 3);
        el = el.parentElement;
      }
      return [255, 255, 255];
    };
    const out: string[] = [];
    document.querySelectorAll(sel).forEach((el) => {
      const text = (el as HTMLElement).innerText?.trim();
      if (!text) return;
      const style = getComputedStyle(el);
      if (style.visibility === "hidden" || style.display === "none") return;
      const fg = parse(style.color).slice(0, 3);
      const bg = bgOf(el);
      const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
      const ratio = (a + 0.05) / (b + 0.05);
      if (ratio < 4.5) out.push(`${text.slice(0, 40)}: ${ratio.toFixed(2)}`);
    });
    return out;
  }, selector);
}
