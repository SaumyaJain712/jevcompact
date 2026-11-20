"""Preview agent sessions for UI tests and screenshots until data/samples/ exists (phase f).

Usage: python scripts/preview_sessions.py OUT_DIR
Writes checkout-bugfix-0412.json, api-refactor-long.json, data-pipeline-test.json and docs-migration.json.
The tool outputs are synthetic filler; the real, hand-labelled samples live in data/samples/.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from factories import Step, build, filler  # noqa: E402

cart_ts = """import { Item } from './types';

export function cartTotal(items: Item[]): number {
  let total;
  for (const item of items) {
    total += item.price * item.qty;
  }
  return total;
}
""" + filler(2500, "cart")

checkout = [
    Step("ls node_modules", "\n".join(f"@scope/package-{i % 400}  lib  dist  README.md" for i in range(6000))),
    Step("cat package.json", '{\n  "name": "shop-web",\n  "scripts": {"test": "jest"}\n}\n' + filler(1500, "pkg")),
    Step("cat package-lock.json", filler(24000, "lock")),
    Step("cat src/cart.ts", cart_ts),
    Step("grep -rn price src/", "src/cart.ts:6:    total += item.price * item.qty;\nsrc/checkout.ts:41: const price = cartTotal(items);\n" + filler(3000, "grep")),
    Step("git log --oneline -n 200", filler(6000, "git")),
    Step("cat README.md", filler(9000, "readme")),
    Step("find . -name '*.test.ts'", "\n".join(f"./src/feature{i}/feature{i}.test.ts" for i in range(900))),
    Step("cat src/checkout.ts", filler(8000, "checkout")),
    Step("npm test", "FAIL src/cart.test.ts\n  ● cartTotal › sums prices\n    TypeError: total is undefined (cart.ts:88)\n" + filler(600, "jest"),
         user_after="Please keep the public API of cartTotal unchanged."),
    Step("cat docs/architecture.md", filler(14000, "arch")),
    Step("cat src/types.ts", filler(5000, "types")),
    Step("npm run lint", filler(12000, "lint")),
    Step("cat coverage/lcov.info", filler(30000, "lcov")),
    Step("cat src/legacy/pricing.ts", filler(20000, "legacy")),
    Step("cat CHANGELOG.md", filler(16000, "changelog")),
    Step("cat src/cart.ts", "export function cartTotal(items: Item[]): number {\n  let total = 0;\n" + filler(400, "fix")),
    Step("npm test", "PASS src/cart.test.ts\nTests: 48 passed, 48 total"),
]

api_steps = [Step(f"cat src/api/v1/{name}.ts", filler(9000, name)) for name in
             ["users", "orders", "payments", "auth", "search", "inventory", "shipping", "reviews",
              "coupons", "admin", "webhooks", "reports", "exports", "imports", "audit"]]
api_steps.insert(3, Step("grep -rn 'router.get' src/api", filler(4000, "routes")))
api_steps.append(Step("npx tsc --noEmit", "src/api/v2/orders.ts(14,7): error TS2322: Type 'string' is not assignable to type 'number'."))

pipe_files = [f"pipelines/stage_{i}.py" for i in range(14)]
pipe_task = "Fix the failing data pipeline test. The bug is in one of: " + ", ".join(pipe_files) + "."
pipe_steps = [Step(f"cat {p}", filler(9500, f"stage{i}")) for i, p in enumerate(pipe_files)]
pipe_steps.append(Step("pytest tests/test_pipeline.py", "1 failed, 31 passed\nAssertionError: expected 1204 rows, got 1188"))

docs_steps = [Step(f"cat docs/{d}.md", filler(3500, d)) for d in ["intro", "install", "config", "api", "faq", "deploy"]]
docs_steps.append(Step("mkdocs build", "INFO - Documentation built in 2.31 seconds"))



SESSIONS = {
    "checkout-bugfix-0412": build(checkout, "openai"),
    "api-refactor-long": build(api_steps, "anthropic", task="Move the REST handlers in src/api/v1 to src/api/v2 with typed responses."),
    "data-pipeline-test": build(pipe_steps, "openai", task=pipe_task),
    "docs-migration": build(docs_steps, "openai", task="Migrate the docs from Sphinx to MkDocs."),
}

if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for name, msgs in SESSIONS.items():
        (out / f"{name}.json").write_text(json.dumps(msgs))
        print(out / f"{name}.json")
