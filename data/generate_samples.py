"""Generate the sample agent sessions and their hand labels.

    python data/generate_samples.py          # writes data/samples/*.json and eval/LABELS.md

Each step's `needed` label says whether that tool result is needed to finish
the task, decided from the task itself (the file that gets fixed, the failing
test, the config that causes the bug) and written here before any judge was
run. The reasons are listed in eval/LABELS.md for review.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from content import (changelog, eslint_output, find_files, git_log, jest_pass, lcov, log_lines,  # noqa: E402
                     ls_node_modules, markdown_doc, package_lock, pip_freeze, py_module, ts_module)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "samples"


@dataclass
class Step:
    command: str
    output: str
    needed: bool
    reason: str
    why: str = ""  # assistant text before the call
    is_error: bool = False
    user_after: str | None = None
    tool: str = "bash"


@dataclass
class Scenario:
    name: str
    fmt: str
    task: str
    steps: list[Step]
    final: str
    system: str = "You are a senior software engineer working in the user's repository. Use the tools to inspect and change code."


# =============================================================================
# 1. checkout-bugfix-0412 (OpenAI format)
# =============================================================================

def cart_ts(fixed: bool = False) -> str:
    head = [
        "import { Money, money, addMoney, multiplyMoney, ZERO } from './money';",
        "import type { CartItem, Cart, Coupon } from './types/cart';",
        "import { logger } from './lib/logger';",
        "",
        "/** Maximum quantity of a single SKU in one cart. */",
        "export const MAX_QTY = 99;",
        "",
        "export function clampQty(qty: number): number {",
        "  if (!Number.isFinite(qty) || qty < 1) return 1;",
        "  return Math.min(Math.floor(qty), MAX_QTY);",
        "}",
        "",
        "export function findItem(cart: Cart, sku: string): CartItem | undefined {",
        "  return cart.items.find((i) => i.sku === sku);",
        "}",
        "",
        "export function addItem(cart: Cart, item: CartItem): Cart {",
        "  const existing = findItem(cart, item.sku);",
        "  if (existing) {",
        "    return {",
        "      ...cart,",
        "      items: cart.items.map((i) => (i.sku === item.sku ? { ...i, qty: clampQty(i.qty + item.qty) } : i)),",
        "    };",
        "  }",
        "  return { ...cart, items: [...cart.items, { ...item, qty: clampQty(item.qty) }] };",
        "}",
        "",
        "export function removeItem(cart: Cart, sku: string): Cart {",
        "  return { ...cart, items: cart.items.filter((i) => i.sku !== sku) };",
        "}",
        "",
        "export function setQty(cart: Cart, sku: string, qty: number): Cart {",
        "  if (qty <= 0) return removeItem(cart, sku);",
        "  return { ...cart, items: cart.items.map((i) => (i.sku === sku ? { ...i, qty: clampQty(qty) } : i)) };",
        "}",
        "",
        "export function itemCount(cart: Cart): number {",
        "  return cart.items.reduce((n, i) => n + i.qty, 0);",
        "}",
        "",
        "export function applyCoupon(cart: Cart, coupon: Coupon): Cart {",
        "  if (coupon.expiresAt && new Date(coupon.expiresAt) < new Date()) {",
        "    logger.info('coupon expired', { code: coupon.code });",
        "    return cart;",
        "  }",
        "  return { ...cart, coupon };",
        "}",
        "",
        "function couponDiscount(subtotal: Money, coupon?: Coupon): Money {",
        "  if (!coupon) return ZERO;",
        "  if (coupon.kind === 'percent') return money(Math.round((subtotal.cents * coupon.value) / 100));",
        "  return money(Math.min(coupon.value, subtotal.cents));",
        "}",
        "",
        "export function shippingFor(subtotal: Money): Money {",
        "  return subtotal.cents >= 5000 ? ZERO : money(499);",
        "}",
        "",
        "export function isEmpty(cart: Cart): boolean {",
        "  return cart.items.length === 0;",
        "}",
        "",
        "export function hasSku(cart: Cart, sku: string): boolean {",
        "  return cart.items.some((i) => i.sku === sku);",
        "}",
        "",
        "export function lineTotal(item: CartItem): Money {",
        "  return multiplyMoney(money(item.priceCents), item.qty);",
        "}",
        "",
        "/**",
        " * Cart total in cents: subtotal minus coupon discount plus shipping.",
        " * Public API: used by checkout.ts and the order summary component.",
        " */",
        "export function cartTotal(cart: Cart): Money {",
    ]
    # pad with blank/comment lines so the buggy line is line 88
    body_start = [
        "  // NOTE: priceCents is an integer number of cents (see types/cart.ts).",
    ]
    if fixed:
        acc = ["  let total: Money = ZERO;"]
    else:
        acc = ["  let total: Money | undefined;"]
    loop = [
        "  for (const item of cart.items) {",
        "    if (item.qty <= 0) continue;",
    ]
    lines = head + body_start + acc + loop
    while len(lines) < 87:
        lines.insert(len(head) + 1, "  //")
    if fixed:
        lines.append("    total = addMoney(total, lineTotal(item));")
    else:
        lines.append("    total.cents += item.priceCents * item.qty;")
    assert fixed or len(lines) == 88
    lines += [
        "  }",
        "  const subtotal = total ?? ZERO;" if not fixed else "  const subtotal = total;",
        "  const discount = couponDiscount(subtotal, cart.coupon);",
        "  return addMoney(money(subtotal.cents - discount.cents), shippingFor(subtotal));",
        "}",
    ]
    return "\n".join(lines) + "\n"


TYPES_CART = """export type Sku = string;

export interface CartItem {
  sku: Sku;
  name: string;
  /** Unit price in integer cents, e.g. 1999 = $19.99 */
  priceCents: number;
  qty: number;
  imageUrl?: string;
}

export interface Coupon {
  code: string;
  kind: 'percent' | 'fixed';
  /** percent: 0-100, fixed: cents */
  value: number;
  expiresAt?: string;
}

export interface Cart {
  id: string;
  currency: 'USD' | 'EUR' | 'GBP';
  items: CartItem[];
  coupon?: Coupon;
  updatedAt: string;
}
"""

MONEY_TS = """/** Money is always handled as integer cents to avoid float rounding errors. */
export interface Money {
  cents: number;
}

export const ZERO: Money = Object.freeze({ cents: 0 });

export function money(cents: number): Money {
  if (!Number.isInteger(cents)) throw new Error(`money(): cents must be an integer, got ${cents}`);
  return { cents };
}

export function addMoney(a: Money, b: Money): Money {
  return { cents: a.cents + b.cents };
}

export function multiplyMoney(a: Money, factor: number): Money {
  return { cents: Math.round(a.cents * factor) };
}

export function formatMoney(m: Money, currency = 'USD', locale = 'en-US'): string {
  return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(m.cents / 100);
}
"""

CART_TEST = """import { cartTotal, addItem, applyCoupon } from './cart';
import type { Cart } from './types/cart';

const empty: Cart = { id: 'c1', currency: 'USD', items: [], updatedAt: '2026-04-12T09:00:00Z' };

describe('cartTotal', () => {
  it('is zero plus shipping for an empty cart', () => {
    expect(cartTotal(empty)).toEqual({ cents: 499 });
  });

  it('sums prices', () => {
    const cart = addItem(addItem(empty, { sku: 'A', name: 'Mug', priceCents: 1299, qty: 2 }),
      { sku: 'B', name: 'Tea', priceCents: 899, qty: 1 });
    expect(cartTotal(cart)).toEqual({ cents: 1299 * 2 + 899 + 499 });
  });

  it('gives free shipping from $50', () => {
    const cart = addItem(empty, { sku: 'C', name: 'Kettle', priceCents: 5400, qty: 1 });
    expect(cartTotal(cart)).toEqual({ cents: 5400 });
  });

  it('applies a percent coupon to the subtotal only', () => {
    const cart = applyCoupon(addItem(empty, { sku: 'A', name: 'Mug', priceCents: 2000, qty: 1 }),
      { code: 'TEN', kind: 'percent', value: 10 });
    expect(cartTotal(cart)).toEqual({ cents: 1800 + 499 });
  });

  it('ignores zero-quantity lines', () => {
    const cart: Cart = { ...empty, items: [{ sku: 'Z', name: 'Ghost', priceCents: 999, qty: 0 }] };
    expect(cartTotal(cart)).toEqual({ cents: 499 });
  });
});
""" + "\n".join(f"""
describe('cartTotal regression {i}', () => {{
  it('handles {n} units of sku R{i}', () => {{
    const cart = addItem(empty, {{ sku: 'R{i}', name: 'Item {i}', priceCents: {100 + i * 37}, qty: {n} }});
    expect(cartTotal(cart).cents).toBeGreaterThan(0);
  }});
}});""" for i, n in zip(range(40), [1, 2, 3, 5, 8] * 8))

NPM_TEST_FAIL = """> shop-web@3.14.0 test
> jest

PASS src/money.test.ts
PASS src/checkout/checkout.test.ts
PASS src/components/OrderSummary.test.tsx
FAIL src/cart.test.ts
  ● cartTotal › sums prices

    TypeError: total is undefined (cart.ts:88)

      86 |   for (const item of cart.items) {
      87 |     if (item.qty <= 0) continue;
    > 88 |     total.cents += item.priceCents * item.qty;
         |           ^
      89 |   }
      90 |   const subtotal = total ?? ZERO;

      at cartTotal (src/cart.ts:88:11)
      at Object.<anonymous> (src/cart.test.ts:14:12)

  ● cartTotal › gives free shipping from $50

    TypeError: total is undefined (cart.ts:88)

      at cartTotal (src/cart.ts:88:11)

  ● cartTotal › applies a percent coupon to the subtotal only

    TypeError: total is undefined (cart.ts:88)

      at cartTotal (src/cart.ts:88:11)

Test Suites: 1 failed, 3 passed, 4 total
Tests:       43 failed, 31 passed, 74 total
Snapshots:   0 total
Time:        4.912 s
Ran all test suites.
npm ERR! Test failed.  See above for more details.
"""

SRC_FILES = [f"src/{d}/{f}.ts" for d in ["checkout", "components", "lib", "api", "hooks", "legacy"]
             for f in ["index", "client", "utils", "constants", "format", "store", "selectors", "routes"]]


def grep_price() -> str:
    hits = ["src/cart.ts:66:  return multiplyMoney(money(item.priceCents), item.qty);",
            "src/cart.ts:88:    total.cents += item.priceCents * item.qty;",
            "src/types/cart.ts:7:  priceCents: number;",
            "src/checkout/checkout.ts:41:  const price = cartTotal(cart);",
            "src/checkout/checkout.ts:57:  analytics.track('checkout_started', { price: price.cents });",
            "src/components/OrderSummary.tsx:22:  const total = formatMoney(cartTotal(cart), cart.currency);",
            "src/components/ProductCard.tsx:31:      <span className=\"price\">{formatMoney(money(p.priceCents))}</span>",
            "src/money.ts:3:/** Money is always handled as integer cents to avoid float rounding errors. */"]
    for i in range(140):
        hits.append(f"src/legacy/pricing-v1.ts:{100 + i * 7}:  // legacy price rule {i}: price = basePrice * (1 - discount{i % 9})")
    return "\n".join(hits)


def checkout_scenario() -> Scenario:
    steps = [
        Step("ls", "README.md\nCHANGELOG.md\ncoverage\ndocs\njest.config.js\nnode_modules\npackage-lock.json\n"
                   "package.json\nsrc\ntsconfig.json", False, "Orientation only; the layout is not needed later.",
             "Let me look at the repository layout."),
        Step("ls -la node_modules", ls_node_modules(700, "checkout"), False, "Installed packages; nothing in the task depends on them.",
             "Checking which test framework is installed."),
        Step("cat package.json", '{\n  "name": "shop-web",\n  "version": "3.14.0",\n  "private": true,\n'
             '  "scripts": {\n    "test": "jest",\n    "lint": "eslint src --ext .ts,.tsx",\n    "build": "vite build"\n  },\n'
             '  "dependencies": {\n    "react": "18.3.1",\n    "react-dom": "18.3.1"\n  },\n'
             '  "devDependencies": {\n    "jest": "29.7.0",\n    "ts-jest": "29.2.5",\n    "typescript": "5.6.3"\n  }\n}',
             False, "Only confirms the test command (`jest`), which was already run.", "Reading package.json for the test script."),
        Step("cat package-lock.json", package_lock(420, "checkout"), False, "Lockfile; irrelevant to a logic bug.",
             "Checking dependency versions in the lockfile."),
        Step("npm test", NPM_TEST_FAIL, True, "The failing test and the exact error location (cart.ts:88).",
             "Running the test suite to see the failure.", is_error=True),
        Step("cat src/cart.ts", cart_ts(), True, "The file that contains the bug and is edited.",
             "The error points at src/cart.ts line 88. Reading it."),
        Step("grep -rn price src/", grep_price(), True, "Shows every use of priceCents and that prices are integer cents.",
             "Searching for how prices are used across the code."),
        Step("cat src/types/cart.ts", TYPES_CART, True, "Defines CartItem.priceCents (integer cents), needed for a correct fix.",
             "Checking the CartItem type."),
        Step("cat src/money.ts", MONEY_TS, True, "Provides ZERO and addMoney, which the fix uses.",
             "Looking at the money helpers used by cart.ts."),
        Step("git log --oneline -n 400", git_log(400, "checkout"), False, "History; the bug is visible in the code itself.",
             "Checking recent history of the repo."),
        Step("cat README.md", markdown_doc("shop-web", 60, "checkout-readme"), False, "General project readme.",
             "Reading the README for conventions."),
        Step("cat docs/architecture.md", markdown_doc("Architecture", 90, "checkout-arch"), False, "Architecture overview; not needed for this fix.",
             "Skimming the architecture doc."),
        Step("cat src/checkout/checkout.ts", ts_module("checkout", 26, "checkout-ts"), False,
             "Caller of cartTotal; the public API must stay the same, so its code is not needed.",
             "Checking how checkout calls cartTotal.", user_after="Please don't change the public API of cartTotal."),
        Step("npm run lint", eslint_output(SRC_FILES * 2, "checkout"), False, "Lint warnings unrelated to the bug.",
             "Running the linter."),
        Step("cat coverage/lcov.info", lcov(SRC_FILES, "checkout"), False, "Coverage data; not needed.",
             "Looking at test coverage for cart.ts."),
        Step("cat src/legacy/pricing-v1.ts", ts_module("pricing-v1", 60, "legacy-pricing"), False, "Legacy pricing module not used by cartTotal.",
             "Checking the legacy pricing module in case it is still used."),
        Step("cat CHANGELOG.md", changelog(70, "checkout"), False, "Release notes; not needed.", "Reading the changelog."),
        Step("cat src/cart.test.ts", CART_TEST, True, "The expectations the fix must satisfy (free shipping, coupon, zero qty).",
             "Reading the failing test's expectations."),
        Step("apply_patch src/cart.ts",
             "*** Begin Patch\n*** Update File: src/cart.ts\n@@ export function cartTotal(cart: Cart): Money {\n"
             "-  let total: Money | undefined;\n+  let total: Money = ZERO;\n@@\n"
             "-    total.cents += item.priceCents * item.qty;\n+    total = addMoney(total, lineTotal(item));\n"
             "@@\n-  const subtotal = total ?? ZERO;\n+  const subtotal = total;\n*** End Patch\nPatched src/cart.ts (3 hunks)",
             True, "The change that was made; needed to report the fix.", "Initialising total to ZERO and using addMoney."),
        Step("npm test", jest_pass(["src/money.test.ts", "src/checkout/checkout.test.ts",
                                    "src/components/OrderSummary.test.tsx", "src/cart.test.ts"], 74),
             True, "Proves the fix works.", "Re-running the tests."),
    ]
    return Scenario("checkout-bugfix-0412", "openai",
                    "The checkout total is wrong and `npm test` fails in src/cart.test.ts. Find and fix the bug in "
                    "the cart total calculation (src/cart.ts) without changing its public API.",
                    steps, "Fixed: cartTotal started from an undefined total. It now starts from ZERO and adds each "
                           "line with addMoney; all 74 tests pass and the public API is unchanged.")


# =============================================================================
# 2. api-refactor-long (Anthropic format)
# =============================================================================

def v1_handler(entity: str, extra: int) -> str:
    E = entity.capitalize()
    base = f"""import {{ Router, Request, Response }} from 'express';
import {{ db }} from '../../db';
import {{ requireAuth }} from '../../auth/middleware';

export const {entity}Router = Router();

// GET /api/v1/{entity}s/:id  -> untyped JSON, legacy field names
{entity}Router.get('/:id', requireAuth, async (req: Request, res: Response) => {{
  const row = await db.{entity}s.findById(req.params.id);
  if (!row) return res.status(404).json({{ error: '{entity} not found' }});
  res.json({{
    id: row.id,
    status: row.status,
    total_cents: row.totalCents,
    created: row.createdAt,
    customer_id: row.customerId,
  }});
}});

// GET /api/v1/{entity}s?customer=...
{entity}Router.get('/', requireAuth, async (req: Request, res: Response) => {{
  const rows = await db.{entity}s.list({{ customerId: String(req.query.customer ?? '') }});
  res.json(rows.map((r) => ({{ id: r.id, status: r.status, total_cents: r.totalCents }})));
}});

// POST /api/v1/{entity}s
{entity}Router.post('/', requireAuth, async (req: Request, res: Response) => {{
  const created = await db.{entity}s.create(req.body);
  res.status(201).json({{ id: created.id }});
}});
"""
    return base + "\n" + ts_module(f"{entity}-helpers", extra, f"v1-{entity}")


V2_TYPES = """// Typed response envelopes for API v2.
export interface ApiResponse<T> {
  data: T;
  meta: { requestId: string; version: 'v2' };
}

export interface ApiError {
  error: { code: 'not_found' | 'invalid' | 'unauthorized' | 'internal'; message: string };
  meta: { requestId: string; version: 'v2' };
}

export interface OrderDto {
  id: string;
  status: 'pending' | 'paid' | 'shipped' | 'cancelled';
  totalCents: number;
  createdAt: string;
  customerId: string;
}

export interface PaymentDto {
  id: string;
  orderId: string;
  amountCents: number;
  method: 'card' | 'paypal' | 'bank_transfer';
  capturedAt: string | null;
}

export function ok<T>(data: T, requestId: string): ApiResponse<T> {
  return { data, meta: { requestId, version: 'v2' } };
}
"""


def openapi_yaml() -> str:
    parts = ["openapi: 3.1.0", "info:", "  title: Shop API", "  version: 2.0.0", "paths:"]
    for ent in ["orders", "payments", "users", "products", "reviews", "coupons", "shipments", "inventory",
                "refunds", "invoices", "wishlists", "addresses", "subscriptions", "reports"]:
        for verb, path in [("get", f"/v2/{ent}/{{id}}"), ("get", f"/v2/{ent}"), ("post", f"/v2/{ent}")]:
            parts += [f"  {path}:" if verb == "get" or path.endswith(ent) else "", f"    {verb}:",
                      f"      operationId: {verb}{ent.capitalize()}",
                      f"      tags: [{ent}]", "      responses:", "        '200':",
                      "          description: OK", "          content:", "            application/json:",
                      "              schema:", f"                $ref: '#/components/schemas/{ent.capitalize()}Response'",
                      "        '404':", "          $ref: '#/components/responses/NotFound'"]
    parts += ["components:", "  schemas:"]
    for ent in ["Order", "Payment", "User", "Product", "Review", "Coupon"]:
        parts += [f"    {ent}Dto:", "      type: object", "      required: [id]", "      properties:",
                  "        id: {type: string}", "        status: {type: string}", "        totalCents: {type: integer}",
                  "        createdAt: {type: string, format: date-time}"]
    return "\n".join(p for p in parts if p)


TSC_ERRORS = """src/api/v2/orders.ts(14,7): error TS2322: Type 'string' is not assignable to type 'number'.
  14       totalCents: row.total_cents,
           ~~~~~~~~~~
src/api/v2/payments.ts(22,5): error TS2741: Property 'capturedAt' is missing in type '{ id: string; orderId: string; amountCents: number; method: string; }' but required in type 'PaymentDto'.
src/api/v2/payments.ts(23,15): error TS2322: Type 'string' is not assignable to type '"card" | "paypal" | "bank_transfer"'.

Found 3 errors in 2 files.

Errors  Files
     1  src/api/v2/orders.ts:14
     2  src/api/v2/payments.ts:22
"""


def api_scenario() -> Scenario:
    v1 = ["orders", "payments", "users", "search", "inventory", "reviews", "coupons", "reports", "webhooks", "admin"]
    steps = [
        Step("ls src/api/v1", "\n".join(f"{e}.ts" for e in v1), False, "Directory listing; the two files in scope are named in the task.",
             "Listing the v1 handlers."),
        Step("cat src/api/v1/orders.ts", v1_handler("order", 34), True, "In scope: the orders handler being moved to v2.",
             "Starting with the orders handler."),
        Step("cat src/api/v1/payments.ts", v1_handler("payment", 34), True, "In scope: the payments handler being moved to v2.",
             "Now the payments handler."),
        Step("cat src/api/v1/users.ts", v1_handler("user", 40), False, "Users are out of scope for this task.",
             "Checking users for shared patterns."),
        Step("cat src/api/v1/search.ts", v1_handler("search", 40), False, "Out of scope.", "Checking search."),
        Step("cat openapi.yaml", openapi_yaml(), True, "Defines the v2 response schemas the typed handlers must follow.",
             "Reading the OpenAPI spec for the v2 schemas."),
        Step("cat src/api/v2/types.ts", V2_TYPES, True, "OrderDto, PaymentDto and the ok() envelope used by the new handlers.",
             "Reading the v2 types."),
        Step("grep -rn \"Router()\" src/api", "\n".join(
            [f"src/api/v1/{e}.ts:5:export const {e.rstrip('s')}Router = Router();" for e in v1]
            + ["src/api/index.ts:12:app.use('/api/v1/orders', orderRouter);",
               "src/api/index.ts:13:app.use('/api/v1/payments', paymentRouter);"]), True,
             "Shows where routers are mounted, which the v1 adapters must keep working.", "Finding where routers are mounted.",
             user_after="Keep the v1 adapters thin — they should just map v2 responses to the old shape."),
        Step("npm ls --all", "\n".join(f"├── {p}@{i % 9}.{i % 13}.{i % 7}" for i, p in enumerate(
            [x for x in ls_node_modules(600, "api").split() if x.islower() and "-" in x][:900])), False,
             "Dependency tree; not needed.", "Listing installed packages."),
        Step("cat node_modules/@types/express-serve-static-core/index.d.ts", ts_module("express-types", 90, "express-dts"), False,
             "Library typings; the needed Request/Response usage is already in the handlers.", "Checking Express typings."),
        Step("docker compose logs api --tail 3000", log_lines(2600, "api", "api-logs"), False, "Runtime logs; unrelated to the refactor.",
             "Checking the API container logs."),
        Step("cat src/api/v1/inventory.ts", v1_handler("inventory", 45), False, "Out of scope.", "Checking inventory."),
        Step("cat src/api/v1/reviews.ts", v1_handler("review", 45), False, "Out of scope.", "Checking reviews."),
        Step("cat tests/api/orders.test.ts", "\n".join(
            ["import request from 'supertest';", "import { app } from '../../src/app';", ""]
            + [f"it('GET /api/{v}/orders/{i} returns {s}', async () => {{\n  const res = await request(app).get('/api/{v}/orders/{i}');\n"
               f"  expect(res.status).toBe({s});\n  expect(res.body{'.data' if v == 'v2' else ''}.{'totalCents' if v == 'v2' else 'total_cents'}).toBeDefined();\n}});"
               for i in range(60) for v, s in [("v1", 200), ("v2", 200)]]), True,
             "Tests for both v1 and v2 order responses; the refactor must pass them.", "Reading the order API tests."),
        Step("cat src/api/v1/reports.ts", v1_handler("report", 50), False, "Out of scope.", "Checking reports."),
        Step("cat src/api/v1/webhooks.ts", v1_handler("webhook", 60), False, "Out of scope.", "Checking webhooks."),
        Step("cat docs/api-guidelines.md", markdown_doc("API guidelines", 80, "api-guide"), False,
             "General guidelines; the concrete types are in types.ts and openapi.yaml.", "Reading the API guidelines."),
        Step("npx tsc --noEmit", TSC_ERRORS, True, "Type errors in the new v2 handlers that must be fixed.",
             "Type-checking the new v2 handlers.", is_error=True),
        Step("git diff --stat", " src/api/v1/orders.ts   | 48 ++++-------\n src/api/v1/payments.ts | 51 ++++-------\n"
             " src/api/v2/orders.ts   | 62 +++++++++++\n src/api/v2/payments.ts | 70 +++++++++++\n"
             " 4 files changed, 152 insertions(+), 79 deletions(-)", True, "Summary of the changes made so far.",
             "Checking what changed."),
    ]
    return Scenario("api-refactor-long", "anthropic",
                    "Move the REST handlers for orders and payments from src/api/v1 to src/api/v2 with typed responses "
                    "(see src/api/v2/types.ts and openapi.yaml). Keep the v1 routes working through thin adapters.",
                    steps, "Moved orders and payments to v2 with typed envelopes; v1 routes now adapt the v2 "
                           "responses. Two type errors remain in payments.ts, which I'm fixing next.")


# =============================================================================
# 3. data-pipeline-test (OpenAI format)
# =============================================================================

ROLLUP_PY = '''"""Daily rollup: one row per (user_id, day) with event counts and revenue."""
from __future__ import annotations

import pandas as pd

from pipelines.dedupe import drop_duplicate_events
from pipelines.io import read_events


def daily_rollup(path: str, tz: str = "UTC") -> pd.DataFrame:
    events = read_events(path)
    events = drop_duplicate_events(events)
    events["day"] = events["ts"].dt.tz_convert(tz).dt.date
    out = (events.groupby(["user_id", "day"])
                 .agg(events=("event_id", "count"), revenue_cents=("amount_cents", "sum"))
                 .reset_index())
    return out
'''

DEDUPE_PY = '''"""Remove duplicate events delivered twice by the collector."""
from __future__ import annotations

import pandas as pd


def drop_duplicate_events(df: pd.DataFrame) -> pd.DataFrame:
    # Collector retries can resend an event; duplicates share user, type and timestamp.
    # BUG? ts is truncated to the minute here, so two genuine events in the same minute collapse.
    key = df["user_id"].astype(str) + "|" + df["event_type"] + "|" + df["ts"].dt.floor("min").astype(str)
    return df.loc[~key.duplicated()].copy()
'''

PYTEST_FAIL = """============================= test session starts ==============================
platform linux -- Python 3.11.10, pytest-8.3.3, pluggy-1.5.0
rootdir: /repo
collected 32 items

tests/test_io.py ......                                                  [ 18%]
tests/test_dedupe.py ....                                                [ 31%]
tests/test_pipeline.py .....F...........                                 [ 84%]
tests/test_schema.py .....                                               [100%]

=================================== FAILURES ===================================
____________________________ test_daily_rollup ____________________________

    def test_daily_rollup():
        out = daily_rollup("tests/fixtures/events_2026-04-01.csv")
>       assert out["events"].sum() == 1204
E       AssertionError: assert 1188 == 1204
E        +  where 1188 = <bound method NDFrame._add_numeric_operations.<locals>.sum>()

tests/test_pipeline.py:41: AssertionError
=========================== short test summary info ============================
FAILED tests/test_pipeline.py::test_daily_rollup - AssertionError: assert 1188 == 1204
========================= 1 failed, 31 passed in 3.82s =========================
"""


def events_csv(rows: int) -> str:
    from content import rng_for

    r = rng_for("events")
    out = ["event_id,user_id,event_type,ts,amount_cents"]
    for i in range(rows):
        m = r.randint(0, 59)
        out.append(f"e{i:06d},u{r.randint(1, 80):03d},{r.choice(['view', 'add_to_cart', 'purchase'])},"
                   f"2026-04-01T{r.randint(0, 23):02d}:{m:02d}:{r.randint(0, 59):02d}Z,{r.choice([0, 0, 0, 1299, 2499])}")
    # genuine same-minute events from one user: these are the ones dedupe wrongly drops
    out += [f"e9{i:05d},u042,view,2026-04-01T10:15:{s:02d}Z,0" for i, s in enumerate([3, 17, 29, 44])]
    return "\n".join(out)


def pipeline_scenario() -> Scenario:
    stages = ["io", "schema", "enrich", "sessions", "funnels", "attribution", "currency", "exports", "quality", "alerts"]
    steps = [
        Step("pytest -q", PYTEST_FAIL, True, "The failing test: 16 events lost (1188 vs 1204).",
             "Running the tests.", is_error=True),
        Step("cat pipelines/rollup.py", ROLLUP_PY, True, "The function under test; shows dedupe runs before grouping.",
             "Reading the rollup step."),
        Step("cat pipelines/dedupe.py", DEDUPE_PY, True, "Contains the bug: the dedupe key floors ts to the minute.",
             "Reading the dedupe step that runs first."),
        Step("ls -R pipelines data", "\n".join(f"pipelines/{s}.py" for s in stages) + "\n" + "\n".join(
            f"data/raw/events_2026-03-{d:02d}.csv" for d in range(1, 32)), False, "Listing; not needed.", "Listing the project."),
        Step("pip freeze", pip_freeze(), False, "Installed packages; irrelevant.", "Checking package versions."),
        Step("cat pipelines/io.py", py_module("io", 30, "io"), False, "Reading CSVs works; not part of the bug.",
             "Checking how events are read."),
        Step("head -n 3000 tests/fixtures/events_2026-04-01.csv", events_csv(2990), True,
             "The fixture shows genuine events from one user in the same minute, which dedupe collapses.",
             "Looking at the test fixture."),
        Step("cat logs/airflow/daily_rollup/2026-04-01.log", log_lines(1600, "airflow", "airflow"), False,
             "Scheduler log noise; nothing about the bug.", "Checking the last scheduled run."),
        Step("cat pipelines/attribution.py", py_module("attribution", 45, "attr"), False, "Unrelated stage.", "Reading attribution."),
        Step("cat pipelines/funnels.py", py_module("funnels", 45, "funnels"), False, "Unrelated stage.", "Reading funnels."),
        Step("git log -p -n 3 -- pipelines/dedupe.py",
             "commit 7c1e9a24d\nAuthor: Dana Kim\nDate:   Mon Mar 30 16:02:11 2026\n\n    Collapse collector retries "
             "within the same minute\n\ndiff --git a/pipelines/dedupe.py b/pipelines/dedupe.py\n"
             '-    key = df["event_id"]\n+    key = df["user_id"].astype(str) + "|" + df["event_type"] + "|" + '
             'df["ts"].dt.floor("min").astype(str)\n', True, "Shows the recent change that introduced the bug "
             "(dedupe used to key on event_id).", "Checking recent changes to dedupe.py.",
             user_after="If it's the dedupe change, prefer keying on event_id again rather than special-casing the test."),
        Step("cat docs/pipeline.md", markdown_doc("Events pipeline", 40, "pipeline-doc"), False, "General docs.", "Reading the pipeline docs."),
        Step("cat pipelines/quality.py", py_module("quality", 50, "quality"), False, "Unrelated stage.", "Reading quality checks."),
        Step("pytest tests/test_dedupe.py -q", "....\n4 passed in 0.41s", True,
             "Dedupe unit tests still pass, so they need extending.", "Running the dedupe unit tests."),
        Step("cat pipelines/exports.py", py_module("exports", 50, "exports"), False, "Unrelated stage.", "Reading exports."),
        Step("apply_patch pipelines/dedupe.py", "*** Begin Patch\n*** Update File: pipelines/dedupe.py\n"
             '-    key = df["user_id"].astype(str) + "|" + df["event_type"] + "|" + df["ts"].dt.floor("min").astype(str)\n'
             '+    key = df["event_id"]\n*** End Patch\nPatched pipelines/dedupe.py (1 hunk)', True,
             "The fix that was applied.", "Keying duplicates on event_id again."),
        Step("pytest -q", "................................\n32 passed in 3.65s", True, "Proves the fix.", "Re-running all tests."),
    ]
    return Scenario("data-pipeline-test", "openai",
                    "tests/test_pipeline.py::test_daily_rollup fails (expected 1204 events, got 1188). "
                    "Find why events are lost in the daily rollup and fix it.",
                    steps, "The dedupe step keyed on user, type and minute, collapsing genuine events. "
                           "It keys on event_id again and all 32 tests pass.")


# =============================================================================
# 4. docs-migration (Anthropic format, under budget)
# =============================================================================

def docs_scenario() -> Scenario:
    steps = [
        Step("ls docs", "conf.py\nindex.rst\ninstall.rst\nconfig.rst\napi.rst\nfaq.rst\n_static\n_templates", True,
             "The list of pages to migrate.", "Listing the Sphinx docs."),
        Step("cat docs/conf.py", "project = 'shop-web'\nextensions = ['sphinx.ext.autodoc', 'myst_parser']\n"
             "html_theme = 'furo'\nhtml_static_path = ['_static']\n", True, "Theme and extensions to map to MkDocs.",
             "Reading the Sphinx config."),
        Step("cat docs/index.rst", markdown_doc("shop-web documentation", 40, "idx").replace("#", "="), True,
             "Page to convert.", "Reading the index page."),
        Step("cat docs/install.rst", markdown_doc("Installation", 45, "inst"), True, "Page to convert.", "Reading install."),
        Step("cat docs/config.rst", markdown_doc("Configuration", 60, "cfg"), True, "Page to convert.", "Reading config."),
        Step("cat docs/api.rst", markdown_doc("API", 80, "api-doc"), True, "Page to convert.", "Reading API page."),
        Step("pip show sphinx furo", "Name: Sphinx\nVersion: 8.1.3\n---\nName: furo\nVersion: 2024.8.6", False,
             "Versions don't affect the migration.", "Checking Sphinx versions."),
        Step("cat docs/faq.rst", markdown_doc("FAQ", 50, "faq"), True, "Page to convert.", "Reading the FAQ."),
        Step("cat mkdocs.yml", "site_name: shop-web\ntheme:\n  name: material\nnav:\n  - Home: index.md\n"
             "  - Install: install.md\n  - Configuration: config.md\n  - API: api.md\n  - FAQ: faq.md\n", True,
             "The new MkDocs config written for the migration.", "Writing mkdocs.yml.",
             user_after="Use the Material theme, please."),
        Step("mkdocs build --strict", "INFO    -  Cleaning site directory\nINFO    -  Building documentation to directory: site\n"
             "INFO    -  Documentation built in 1.84 seconds", True, "Confirms the migrated site builds.", "Building the site."),
    ]
    return Scenario("docs-migration", "anthropic", "Migrate the project documentation in docs/ from Sphinx (reStructuredText) to MkDocs.",
                    steps, "Converted five pages to Markdown and added mkdocs.yml with the Material theme; the site builds cleanly.")


# =============================================================================
# 5. auth-session-expiry (Anthropic format)
# =============================================================================

SESSION_TS = """import session from 'express-session';
import RedisStore from 'connect-redis';
import { redis } from '../lib/redis';
import { config } from '../config';

// Session lifetime comes from config.auth.sessionTtl (documented in hours? see config/default.json)
export const sessionMiddleware = session({
  store: new RedisStore({ client: redis, prefix: 'sess:' }),
  secret: config.auth.sessionSecret,
  resave: false,
  saveUninitialized: false,
  rolling: true,
  cookie: {
    httpOnly: true,
    secure: config.env === 'production',
    sameSite: 'lax',
    // express-session expects maxAge in MILLISECONDS
    maxAge: config.auth.sessionTtl,
  },
});
"""

CONFIG_JSON = """{
  "env": "development",
  "port": 8080,
  "auth": {
    "sessionSecret": "${SESSION_SECRET}",
    "sessionTtl": 300000,
    "_comment": "sessionTtl was changed from seconds to ms in PR #1932; 24h = 86400000"
  },
  "redis": { "url": "redis://localhost:6379/0" },
  "rateLimit": { "windowMs": 60000, "max": 120 }
}
"""


def auth_scenario() -> Scenario:
    inject = {600: "auth WARN session sess:9f2c expired after 300s (user u_1842) — redirecting to /login",
              1100: "auth WARN session sess:a17b expired after 300s (user u_2210) — redirecting to /login"}
    steps = [
        Step("grep -rn \"maxAge\\|sessionTtl\" src config", "src/auth/session.ts:17:    maxAge: config.auth.sessionTtl,\n"
             "config/default.json:6:    \"sessionTtl\": 300000,\nconfig/production.json:4:    \"sessionTtl\": 300000,\n"
             "src/config/index.ts:22:  sessionTtl: Number(process.env.SESSION_TTL ?? file.auth.sessionTtl),",
             True, "Locates every place the session lifetime is set.", "Searching for where the session lifetime is set."),
        Step("cat src/auth/session.ts", SESSION_TS, True, "The session middleware; maxAge is in milliseconds.",
             "Reading the session middleware."),
        Step("cat config/default.json", CONFIG_JSON, True, "Contains the wrong value: 300000 ms = 5 minutes.",
             "Reading the default config."),
        Step("cat node_modules/express-session/README.md", markdown_doc("express-session", 150, "es-readme"), False,
             "Library readme; the needed fact (maxAge in ms) is already in session.ts.", "Checking the express-session docs."),
        Step("redis-cli --scan --pattern 'sess:*'", "\n".join(f"sess:{i:04x}{i * 7 % 997:03x}" for i in range(5000)), False,
             "List of session keys; not needed.", "Looking at live session keys."),
        Step("kubectl logs deploy/web --since=1h", log_lines(3000, "web", "auth-logs", inject), True,
             "Production log lines prove sessions expire after 300 s.", "Checking production logs for logouts."),
        Step("cat src/routes/account.ts", ts_module("account", 40, "account"), False, "Unrelated routes.", "Reading account routes."),
        Step("cat config/production.json", CONFIG_JSON.replace("development", "production"), True,
             "Production also sets 300000; must be fixed too.", "Reading the production config.",
             user_after="Make sure production gets the 24 h value too."),
        Step("cat docs/security.md", markdown_doc("Security", 40, "sec"), False, "General security docs.", "Reading security docs."),
        Step("git log --oneline -n 300", git_log(300, "auth"), False, "History; the config comment already explains the change.",
             "Checking history."),
        Step("cat src/lib/redis.ts", ts_module("redis", 20, "redis"), False, "Redis client; not part of the bug.", "Reading the redis client."),
        Step("npm test -- auth", "FAIL tests/auth/session.test.ts\n  ● session › keeps users logged in for 24 hours\n\n"
             "    expect(received).toBe(expected)\n\n    Expected: 86400000\n    Received: 300000\n\n"
             "      at Object.<anonymous> (tests/auth/session.test.ts:18:43)\n\nTests: 1 failed, 11 passed, 12 total",
             True, "The test that encodes the 24 h requirement.", "Running the auth tests.", is_error=True),
        Step("cat CHANGELOG.md", changelog(80, "auth"), False, "Release notes.", "Reading the changelog."),
        Step("apply_patch config/default.json config/production.json", "Patched config/default.json (1 hunk)\n"
             "Patched config/production.json (1 hunk)\n-    \"sessionTtl\": 300000,\n+    \"sessionTtl\": 86400000,",
             True, "The fix.", "Setting sessionTtl to 86400000 ms in both configs."),
        Step("npm test -- auth", "PASS tests/auth/session.test.ts\nTests: 12 passed, 12 total", True, "Proves the fix.", "Re-running."),
    ]
    return Scenario("auth-session-expiry", "anthropic",
                    "Users get logged out after 5 minutes instead of 24 hours. Find the cause and fix the session expiry.",
                    steps, "sessionTtl was 300000 ms (5 min) after a seconds→ms change. Set it to 86400000 in default "
                           "and production configs; the auth tests pass.")


# =============================================================================
# 6. flaky-ci-timeout (OpenAI format)
# =============================================================================

CI_YML = """name: ci
on: [push, pull_request]
jobs:
  e2e-tests:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    services:
      postgres:
        image: postgres:16
        env: { POSTGRES_PASSWORD: postgres }
        ports: ['5432:5432']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: npm }
      - run: npm ci
      - run: npx playwright install --with-deps chromium
      - run: npm run db:migrate
      - run: npm run start:test &
      - run: npx playwright test
"""

PW_CONFIG = """import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 30_000,
  retries: 0,
  workers: 4,
  use: { baseURL: 'http://localhost:3000' },
  // no webServer block: CI starts the app in the background and tests begin immediately
});
"""


def ci_log() -> str:
    inject = {2290: "e2e-tests  ✘ checkout.spec.ts:12:5 › guest can pay (30.0s)",
              2291: "e2e-tests    Error: page.goto: net::ERR_CONNECTION_REFUSED at http://localhost:3000/",
              2292: "e2e-tests  Error: The operation was canceled. (job exceeded timeout-minutes: 20)"}
    return log_lines(2300, "e2e-tests", "ci-log", inject)


def ci_scenario() -> Scenario:
    steps = [
        Step("gh run view 9182 --log-failed", ci_log(), True,
             "The failing CI log: connection refused at the start, then the job timeout.",
             "Fetching the failed CI log.", is_error=True),
        Step("cat .github/workflows/ci.yml", CI_YML, True, "Starts the app in the background with no wait before tests.",
             "Reading the workflow."),
        Step("cat playwright.config.ts", PW_CONFIG, True, "No webServer block, so tests do not wait for the app.",
             "Reading the Playwright config."),
        Step("ls node_modules", ls_node_modules(700, "ci"), False, "Installed packages.", "Checking installed packages."),
        Step("cat package-lock.json", package_lock(350, "ci"), False, "Lockfile.", "Checking the lockfile."),
        Step("cat tests/e2e/checkout.spec.ts", ts_module("checkout-spec", 30, "e2e-spec"), True,
             "The test that fails first; confirms it only fails on the first navigation.", "Reading the failing spec."),
        Step("docker logs ci-postgres", log_lines(900, "postgres", "pg-log"), False, "Database logs show nothing wrong.",
             "Checking the database logs."),
        Step("npm ls @playwright/test", "shop-web@3.14.0 /repo\n└── @playwright/test@1.48.2", False,
             "Version is fine.", "Checking the Playwright version."),
        Step("cat docs/testing.md", markdown_doc("Testing", 40, "testing"), False, "General testing docs.", "Reading testing docs."),
        Step("cat src/server/start.ts", ts_module("start", 30, "start"), False, "App start-up is normal.", "Reading server start-up.",
             user_after="Don't just raise the timeout — I want the root cause fixed."),
        Step("git log --oneline -n 300 -- .github", git_log(300, "ci"), False, "History.", "Checking CI history."),
        Step("cat coverage/lcov.info", lcov(SRC_FILES, "ci"), False, "Coverage data.", "Checking coverage."),
        Step("apply_patch playwright.config.ts .github/workflows/ci.yml",
             "Patched playwright.config.ts (adds webServer: { command: 'npm run start:test', url: 'http://localhost:3000/healthz', "
             "reuseExistingServer: !process.env.CI, timeout: 120_000 })\nPatched .github/workflows/ci.yml (removes background start)",
             True, "The fix.", "Letting Playwright start the app and wait for /healthz."),
        Step("npx playwright test --repeat-each 5", "Running 240 tests using 4 workers\n  240 passed (3.9m)", True,
             "Proves the fix is reliable.", "Running the suite five times to check for flakiness."),
    ]
    return Scenario("flaky-ci-timeout", "openai",
                    "The CI job e2e-tests times out intermittently. Find the root cause and make it reliable.",
                    steps, "Tests started before the app was listening. Playwright now starts the app via webServer "
                           "and waits for /healthz; 5 repeated runs pass.")


SCENARIOS = [checkout_scenario, api_scenario, pipeline_scenario, docs_scenario, auth_scenario, ci_scenario]


# =============================================================================
# build messages + labels
# =============================================================================

def build(sc: Scenario) -> tuple[list[dict], dict]:
    msgs: list[dict] = []
    labels = {"session": sc.name, "format": sc.fmt, "task": sc.task, "items": []}
    if sc.fmt == "openai":
        msgs.append({"role": "system", "content": sc.system})
    msgs.append({"role": "user", "content": sc.task})
    for i, s in enumerate(sc.steps):
        cid = f"call_{sc.name[:4]}_{i:02d}"
        args = {"command": s.command}
        if sc.fmt == "openai":
            msgs.append({"role": "assistant", "content": s.why or None,
                         "tool_calls": [{"id": cid, "type": "function",
                                         "function": {"name": s.tool, "arguments": json.dumps(args)}}]})
            msgs.append({"role": "tool", "tool_call_id": cid, "content": s.output})
        else:
            content = ([{"type": "text", "text": s.why}] if s.why else []) + [
                {"type": "tool_use", "id": cid, "name": s.tool, "input": args}]
            msgs.append({"role": "assistant", "content": content})
            block = {"type": "tool_result", "tool_use_id": cid, "content": s.output}
            if s.is_error:
                block["is_error"] = True
            msgs.append({"role": "user", "content": [block]})
        if s.user_after:
            if sc.fmt == "anthropic":
                msgs.append({"role": "assistant", "content": [{"type": "text", "text": "Understood."}]})
                msgs.append({"role": "user", "content": [{"type": "text", "text": s.user_after}]})
            else:
                msgs.append({"role": "user", "content": s.user_after})
        labels["items"].append({"tool_call_id": cid, "command": s.command, "needed": s.needed, "reason": s.reason})
    if sc.fmt == "openai":
        msgs.append({"role": "assistant", "content": sc.final})
    else:
        msgs.append({"role": "assistant", "content": [{"type": "text", "text": sc.final}]})
    return msgs, labels


def main() -> None:
    from jevcompact.formats import total_tokens  # noqa: E402

    OUT.mkdir(parents=True, exist_ok=True)
    md = ["# Hand labels", "",
          "Which tool results are **needed** to finish each task. Written from the task alone, before any judge was run, "
          "by reading what the fix depends on (the file that is changed, the failing test, the config that causes the bug). "
          "Please review and correct: edit `data/generate_samples.py` and re-run it.", "",
          "Generated by `python data/generate_samples.py`.", ""]
    summary = []
    for make in SCENARIOS:
        sc = make()
        msgs, labels = build(sc)
        (OUT / f"{sc.name}.json").write_text(json.dumps(msgs, indent=1, ensure_ascii=False))
        (OUT / f"{sc.name}.labels.json").write_text(json.dumps(labels, indent=2, ensure_ascii=False))
        tokens = total_tokens(msgs)
        n_needed = sum(i["needed"] for i in labels["items"])
        summary.append((sc.name, sc.fmt, len(msgs), tokens, len(labels["items"]), n_needed))
        md += [f"## {sc.name} ({sc.fmt}, {tokens:,} tokens)", "", f"**Task:** {sc.task}", "",
               "| # | Tool call | Needed | Reason |", "|---|---|---|---|"]
        for k, it in enumerate(labels["items"]):
            cmd = it["command"].replace("|", "\\|")
            md.append(f"| {k + 1} | `{cmd}` | {'**yes**' if it['needed'] else 'no'} | {it['reason']} |")
        md.append("")
    md[6:6] = ["| Session | Format | Messages | Tokens | Tool results | Needed |", "|---|---|---|---|---|---|"] + [
        f"| {n} | {f} | {m} | {t:,} | {i} | {nd} |" for n, f, m, t, i, nd in summary] + [""]
    (ROOT / "eval").mkdir(exist_ok=True)
    (ROOT / "eval" / "LABELS.md").write_text("\n".join(md) + "\n")
    for row in summary:
        print("{:22} {:9} msgs={:3} tokens={:>7,} items={:2} needed={:2}".format(*row))


if __name__ == "__main__":
    main()
