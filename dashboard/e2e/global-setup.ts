import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { PREVIEW_DIR, ROOT, SAMPLE_NAMES, SAMPLES_DIR } from "./helpers";
import path from "node:path";

export default async function globalSetup() {
  const haveSamples = SAMPLE_NAMES.every((n) => existsSync(path.join(SAMPLES_DIR, `${n}.json`)));
  if (!haveSamples) {
    const py = path.join(ROOT, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
    execFileSync(py, [path.join(ROOT, "scripts", "preview_sessions.py"), PREVIEW_DIR], { stdio: "ignore" });
  }
}
