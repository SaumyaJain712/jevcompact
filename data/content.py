"""Realistic tool-output building blocks for the sample sessions (seeded, deterministic).

Everything here is plain text an agent would see: source files, directory
listings, lockfiles, test runner output, logs. No judge is involved.
"""
from __future__ import annotations

import base64
import hashlib
import random
from datetime import datetime, timedelta

NPM_PACKAGES = """react react-dom react-router react-router-dom redux @reduxjs/toolkit axios lodash lodash.merge
lodash.debounce date-fns dayjs moment uuid nanoid classnames clsx zod yup joi express body-parser cors helmet
morgan cookie-parser express-session connect-redis ioredis pg pg-pool knex prisma @prisma/client typeorm
sequelize mongoose jsonwebtoken bcrypt bcryptjs passport passport-jwt passport-local dotenv cross-env
webpack webpack-cli webpack-dev-server babel-loader @babel/core @babel/preset-env @babel/preset-react
@babel/preset-typescript @babel/runtime typescript ts-node ts-jest jest jest-environment-jsdom
@testing-library/react @testing-library/jest-dom @testing-library/user-event eslint eslint-config-prettier
eslint-plugin-react eslint-plugin-react-hooks eslint-plugin-import @typescript-eslint/parser
@typescript-eslint/eslint-plugin prettier husky lint-staged postcss autoprefixer tailwindcss sass
css-loader style-loader mini-css-extract-plugin html-webpack-plugin terser-webpack-plugin vite
@vitejs/plugin-react rollup esbuild chalk commander yargs inquirer ora debug semver glob minimatch
rimraf mkdirp fs-extra chokidar ws socket.io socket.io-client graphql apollo-server @apollo/client
stripe @stripe/stripe-js decimal.js big.js currency.js numeral i18next react-i18next intl-messageformat
sharp multer formidable nodemailer winston pino pino-pretty supertest nock msw playwright @playwright/test
cypress puppeteer core-js regenerator-runtime tslib source-map-support acorn ajv ansi-regex ansi-styles
argparse balanced-match brace-expansion braces browserslist caniuse-lite chokidar color-convert
color-name concat-map convert-source-map cross-spawn electron-to-chromium escalade escape-string-regexp
fast-glob fill-range function-bind gensync globals graceful-fs has-flag inherits is-binary-path
is-extglob is-glob is-number js-tokens jsesc json5 lru-cache micromatch ms node-releases normalize-path
once path-is-absolute picocolors picomatch readdirp resolve semver supports-color to-regex-range
update-browserslist-db wrappy yallist""".split()

COMMIT_VERBS = ["Fix", "Add", "Refactor", "Update", "Remove", "Rename", "Bump", "Improve", "Simplify", "Revert"]
COMMIT_OBJECTS = ["checkout flow", "cart badge", "price formatting", "coupon validation", "session cookie",
                  "order history page", "payment retry", "address form", "shipping estimate", "tax rounding",
                  "product grid", "search debounce", "login redirect", "error boundary", "CI cache",
                  "eslint config", "dependency versions", "README", "API client timeout", "analytics events",
                  "feature flags", "image lazy loading", "currency selector", "inventory sync", "admin table"]


def rng_for(*key: object) -> random.Random:
    return random.Random(hashlib.sha256(repr(key).encode()).hexdigest())


def approx_tokens(text: str) -> int:
    return len(text) // 4


# --- listings / lockfiles ------------------------------------------------------

def ls_node_modules(n: int, seed: str = "nm") -> str:
    r = rng_for("ls", seed)
    names = sorted(set(NPM_PACKAGES + [f"{p}-{s}" for p in NPM_PACKAGES[:120]
                                       for s in ("utils", "core", "types", "plugin", "compat")]))
    lines = []
    for name in names[:n]:
        perms = "drwxr-xr-x"
        size = r.choice([4096, 4096, 4096, 8192])
        day = r.randint(1, 28)
        lines.append(f"{perms}  {r.randint(3, 9)} dev  staff  {size:>6}  Mar {day:>2} 10:{r.randint(10, 59)}  {name}")
    return f"total {len(lines) * 8}\n" + "\n".join(lines)


def package_lock(n: int, seed: str = "lock") -> str:
    r = rng_for("lock", seed)
    parts = ['{\n  "name": "shop-web",\n  "version": "3.14.0",\n  "lockfileVersion": 3,\n  "requires": true,\n  "packages": {']
    for i in range(n):
        name = r.choice(NPM_PACKAGES)
        ver = f"{r.randint(0, 9)}.{r.randint(0, 30)}.{r.randint(0, 20)}"
        integrity = base64.b64encode(hashlib.sha512(f"{seed}{i}".encode()).digest()).decode()
        dev = ',\n      "dev": true' if r.random() < 0.6 else ""
        parts.append(
            f'    "node_modules/{name}{"" if i < 150 else f"/node_modules/{r.choice(NPM_PACKAGES)}"}": {{\n'
            f'      "version": "{ver}",\n'
            f'      "resolved": "https://registry.npmjs.org/{name}/-/{name.split("/")[-1]}-{ver}.tgz",\n'
            f'      "integrity": "sha512-{integrity}"{dev}\n    }},')
    parts.append("  }\n}")
    return "\n".join(parts)


def pip_freeze(seed: str = "pip") -> str:
    pkgs = ["pandas==2.2.3", "numpy==2.1.2", "pyarrow==17.0.0", "sqlalchemy==2.0.36", "psycopg2-binary==2.9.10",
            "apache-airflow==2.10.3", "pendulum==3.0.0", "python-dateutil==2.9.0", "pytz==2024.2",
            "pytest==8.3.3", "pytest-cov==6.0.0", "great-expectations==1.2.1", "boto3==1.35.54",
            "botocore==1.35.54", "s3transfer==0.10.3", "requests==2.32.3", "urllib3==2.2.3", "pydantic==2.9.2",
            "pydantic-core==2.23.4", "jinja2==3.1.4", "markupsafe==3.0.2", "click==8.1.7", "rich==13.9.4",
            "tenacity==9.0.0", "structlog==24.4.0", "duckdb==1.1.3", "polars==1.12.0", "fsspec==2024.10.0",
            "s3fs==2024.10.0", "attrs==24.2.0", "packaging==24.2", "six==1.16.0", "tzdata==2024.2"]
    r = rng_for("pip", seed)
    extra = [f"{w}=={r.randint(0, 5)}.{r.randint(0, 20)}.{r.randint(0, 9)}" for w in
             ["alembic", "croniter", "flask", "gunicorn", "marshmallow", "lxml", "openpyxl", "tabulate",
              "termcolor", "typing-extensions", "wrapt", "zipp", "importlib-metadata", "cryptography",
              "cffi", "pycparser", "idna", "certifi", "charset-normalizer", "setuptools"]]
    return "\n".join(sorted(pkgs + extra))


def git_log(n: int, seed: str = "git") -> str:
    r = rng_for("git", seed)
    lines = []
    for i in range(n):
        h = hashlib.sha1(f"{seed}{i}".encode()).hexdigest()[:9]
        lines.append(f"{h} {r.choice(COMMIT_VERBS)} {r.choice(COMMIT_OBJECTS)}"
                     f"{r.choice(['', '', ' (#' + str(r.randint(800, 2400)) + ')'])}")
    return "\n".join(lines)


def find_files(paths: list[str]) -> str:
    return "\n".join(f"./{p}" for p in paths)


# --- source code ----------------------------------------------------------------

DOMAIN = ["order", "invoice", "coupon", "shipment", "customer", "product", "inventory", "refund",
          "address", "payment", "subscription", "review", "wishlist", "promotion", "tax", "warehouse"]


def ts_module(name: str, n_funcs: int, seed: str | None = None) -> str:
    r = rng_for("ts", seed or name)
    ent = r.choice(DOMAIN)
    Ent = ent.capitalize()
    out = [f"import {{ logger }} from '../lib/logger';",
           f"import {{ http }} from '../lib/http';",
           f"import type {{ {Ent}, {Ent}Id, Page }} from '../types';",
           "",
           f"const BASE_URL = '/api/{ent}s';",
           f"const DEFAULT_PAGE_SIZE = {r.choice([20, 25, 50])};",
           ""]
    for i in range(n_funcs):
        verb = r.choice(["fetch", "update", "create", "archive", "validate", "normalize", "list", "sync"])
        fn = f"{verb}{Ent}{r.choice(['', 'Details', 'Summary', 'Batch', 'Status', 'Snapshot'])}{i if r.random() < .3 else ''}"
        out += [f"export async function {fn}(id: {Ent}Id, opts: {{ signal?: AbortSignal }} = {{}}): Promise<{Ent}> {{",
                f"  const started = Date.now();",
                f"  const res = await http.get<{Ent}>(`${{BASE_URL}}/${{id}}`, {{ signal: opts.signal }});",
                f"  if (!res.ok) {{",
                f"    logger.warn('{fn} failed', {{ id, status: res.status }});",
                f"    throw new Error(`{fn}: HTTP ${{res.status}}`);",
                f"  }}",
                f"  const {ent} = res.data;",
                f"  if ({ent}.{r.choice(['updatedAt', 'createdAt', 'version'])} === undefined) {{",
                f"    {ent}.version = {r.randint(1, 4)};",
                f"  }}",
                f"  logger.debug('{fn}', {{ id, ms: Date.now() - started }});",
                f"  return {ent};",
                "}", ""]
        if r.random() < 0.4:
            out += [f"export function is{Ent}Active{i}({ent}: {Ent}): boolean {{",
                    f"  return {ent}.status !== 'archived' && !{ent}.deletedAt;",
                    "}", ""]
    out += [f"export async function list{Ent}s(page = 1, size = DEFAULT_PAGE_SIZE): Promise<Page<{Ent}>> {{",
            f"  const res = await http.get<Page<{Ent}>>(`${{BASE_URL}}?page=${{page}}&size=${{size}}`);",
            "  return res.data;", "}"]
    return "\n".join(out)


def py_module(name: str, n_funcs: int, seed: str | None = None) -> str:
    r = rng_for("py", seed or name)
    out = ['"""' + name.replace("_", " ").capitalize() + ' stage of the events pipeline."""',
           "from __future__ import annotations", "", "import logging",
           "from dataclasses import dataclass", "", "import pandas as pd", "",
           "log = logging.getLogger(__name__)", ""]
    for i in range(n_funcs):
        col = r.choice(["user_id", "session_id", "event_type", "amount", "country", "device", "campaign"])
        fn = f"{r.choice(['clean', 'enrich', 'filter', 'aggregate', 'validate', 'cast'])}_{col}_{i}"
        dtype = r.choice(["str", '"category"', "float"])
        out += [f"def {fn}(df: pd.DataFrame) -> pd.DataFrame:",
                f'    """{fn.replace("_", " ").capitalize()}."""',
                f"    before = len(df)",
                f"    df = df[df[\"{col}\"].notna()].copy()",
                f"    df[\"{col}\"] = df[\"{col}\"].astype({dtype})",
                f"    log.info(\"{fn}: %d -> %d rows\", before, len(df))",
                "    return df", ""]
    return "\n".join(out)


DOC_SENTENCES = [
    "The storefront talks to the order service through the internal API gateway.",
    "Each service owns its own database schema and exposes a small typed interface.",
    "Deployments go through the staging environment before a gradual production rollout.",
    "Metrics are collected per route, and alerts fire when the error budget for a service is spent.",
    "Catalog reads are cached at the edge for five minutes, while writes always go to the primary database.",
    "Feature flags control new behaviour and are removed within two sprints of a full launch.",
    "Run the unit tests locally before opening a pull request; CI runs the full suite on every push.",
    "Configuration is read from environment variables first and from the JSON files in config/ second.",
    "Secrets are injected by the deployment platform and must never be committed to the repository.",
    "Background jobs run in a separate worker process and retry failed tasks with exponential backoff.",
    "The admin dashboard is only reachable from the corporate VPN.",
    "Logs are structured JSON and are shipped to the central log store with a 30 day retention.",
    "On-call engineers can roll back a release from the deployment page in one click.",
    "API responses use camelCase field names, and timestamps are ISO 8601 strings in UTC.",
    "Database migrations are forward-only and must be safe to run while the previous release is live.",
    "Images are resized on upload and stored in the object store with a content hash as the key.",
    "The checkout flow is covered by end-to-end tests that run against a seeded test database.",
    "Rate limits apply per API key and are configured in the gateway, not in the services.",
    "Translations live in locales/ and are loaded lazily per route.",
    "Accessibility checks run as part of the component tests and block the merge when they fail.",
    "Payment provider webhooks are verified with a shared signing secret before they are processed.",
    "Customer data exports are generated asynchronously and expire after seven days.",
    "Search uses a separate index that is rebuilt nightly and updated incrementally on product changes.",
    "The design system components are versioned and published as an internal package.",
    "Performance budgets are enforced in CI: the main bundle must stay under 250 kB gzipped.",
]
SECTION_TITLES = ["Overview", "Architecture", "Deployment", "Configuration", "Testing", "Monitoring", "Data model",
                  "Release process", "Security", "Troubleshooting", "Local development", "Conventions"]


def markdown_doc(title: str, sections: int, seed: str | None = None) -> str:
    r = rng_for("md", seed or title)
    out = [f"# {title}", ""]
    for s in range(sections):
        out += [f"## {r.choice(SECTION_TITLES)} ({s + 1})", ""]
        for _ in range(r.randint(2, 4)):
            out += [" ".join(r.sample(DOC_SENTENCES, r.randint(3, 6))), ""]
        if r.random() < 0.4:
            out += ["```bash", f"npm run {r.choice(['build', 'test', 'deploy:staging', 'lint'])}", "```", ""]
    return "\n".join(out)


def changelog(n: int, seed: str = "changelog") -> str:
    r = rng_for("cl", seed)
    out = ["# Changelog", ""]
    for i in range(n):
        out += [f"## [3.{n - i}.0] - 2026-{r.randint(1, 10):02d}-{r.randint(1, 28):02d}", ""]
        for _ in range(r.randint(2, 6)):
            out.append(f"- {r.choice(COMMIT_VERBS)} {r.choice(COMMIT_OBJECTS)}")
        out.append("")
    return "\n".join(out)


def lcov(files: list[str], seed: str = "lcov") -> str:
    r = rng_for("lcov", seed)
    out = []
    for f in files:
        out += ["TN:", f"SF:{f}"]
        lines = r.randint(40, 160)
        for ln in range(1, lines):
            out.append(f"DA:{ln},{r.choice([0, 1, 1, 2, 4, 12])}")
        out += [f"LF:{lines}", f"LH:{int(lines * r.uniform(.5, .95))}", "end_of_record"]
    return "\n".join(out)


def eslint_output(files: list[str], seed: str = "eslint") -> str:
    r = rng_for("eslint", seed)
    rules = [("warning", "@typescript-eslint/no-explicit-any", "Unexpected any. Specify a different type"),
             ("warning", "react-hooks/exhaustive-deps", "React Hook useEffect has a missing dependency"),
             ("warning", "import/no-unused-modules", "exported declaration not used within other modules"),
             ("warning", "no-console", "Unexpected console statement")]
    out, total = [], 0
    for f in files:
        out.append(f"\n/repo/{f}")
        for _ in range(r.randint(2, 7)):
            sev, rule, msg = r.choice(rules)
            out.append(f"  {r.randint(1, 240)}:{r.randint(1, 60)}  {sev}  {msg}  {rule}")
            total += 1
    out.append(f"\n✖ {total} problems (0 errors, {total} warnings)")
    return "\n".join(out)


def log_lines(n: int, service: str, seed: str, inject: dict[int, str] | None = None) -> str:
    r = rng_for("log", seed)
    t = datetime(2026, 4, 12, 9, 0, 0)
    msgs = ["GET /api/products 200 {ms}ms", "GET /api/cart 200 {ms}ms", "POST /api/cart/items 201 {ms}ms",
            "GET /healthz 200 {ms}ms", "cache hit key=catalog:{n}", "db pool size=10 idle={n}",
            "GET /api/orders/{n} 200 {ms}ms", "job heartbeat worker={n}", "GET /static/app.{n}.js 304 {ms}ms"]
    out = []
    for i in range(n):
        t += timedelta(milliseconds=r.randint(5, 900))
        msg = inject.get(i) if inject and i in inject else r.choice(msgs).format(ms=r.randint(2, 180), n=r.randint(1, 999))
        out.append(f"{t.isoformat(timespec='milliseconds')}Z {service} {r.choice(['INFO', 'INFO', 'INFO', 'DEBUG'])} {msg}")
    return "\n".join(out)


def jest_pass(suites: list[str], tests: int) -> str:
    out = [f"PASS {s}" for s in suites]
    out += ["", f"Test Suites: {len(suites)} passed, {len(suites)} total",
            f"Tests:       {tests} passed, {tests} total", "Snapshots:   0 total", "Time:        6.418 s",
            "Ran all test suites."]
    return "\n".join(out)
