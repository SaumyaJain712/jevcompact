import { defineConfig } from "@playwright/test";
import { execSync } from "node:child_process";
import { rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const E2E_DATA = path.join(ROOT, ".e2e-data");
const BIN = path.join(ROOT, ".venv", process.platform === "win32" ? "Scripts/jevcompact.exe" : "bin/jevcompact");

// Runs once in the main process (workers inherit E2E_PREPARED): fresh data + a fresh build,
// because the API server serves dashboard/dist.
if (!process.env.E2E_PREPARED) {
  rmSync(E2E_DATA, { recursive: true, force: true });
  execSync("npm run build", { cwd: HERE, stdio: "ignore" });
  process.env.E2E_PREPARED = "1";
}

const server = (port: number, name: string, extra: Record<string, string> = {}) => ({
  command: `"${BIN}" serve --port ${port}`,
  url: `http://127.0.0.1:${port}/api/health`,
  reuseExistingServer: false,
  timeout: 60_000,
  env: {
    ...(process.env as Record<string, string>),
    JEVCOMPACT_DATA: path.join(E2E_DATA, name),
    JEVCOMPACT_KEYRING: "0",
    JUDGE: "mock",
    SUMMARIZER: "mock",
    ...extra,
  },
});

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  workers: 1,
  fullyParallel: false,
  reporter: [["list"], ["json", { outputFile: "test-results/results.json" }]],
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: "http://127.0.0.1:8790",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: [
    server(8790, "main"),
    // MockJudge sleeps 6 s here, past Jev's 5 s timeout, so runs genuinely fall back.
    server(8791, "slow", { MOCK_JUDGE_LATENCY_MS: "6000" }),
    // Clean server used only by `npm run screenshots`.
    server(8792, "shots"),
  ],
});
