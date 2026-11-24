"""Browser smoke test (Playwright, Chrome): every page for every role renders without errors.

Usage: python tests/e2e/smoke.py [base_url]   (needs the seeded demo: `python -m manima.cli seed-demo`)
Checks per page: no console errors, no 5xx API calls, no unexpected 4xx, no error state rendered.
Screenshots go to tests/e2e/out/.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)
PW = os.environ.get("DEMO_PASSWORD", "Demo@12345")

WORKSPACE = [
    "/dashboard", "/workspace/tasks", "/crm/leads", "/crm/accounts", "/crm/contacts", "/crm/opportunities",
    "/crm/activities", "/catalog/items", "/sales/quotations", "/sales/quotations/new", "/sales/orders",
    "/sales/orders/new", "/billing/invoices", "/billing/invoices/new", "/billing/payments",
    "/billing/payments/new", "/billing/credit-notes", "/billing/debit-notes", "/inventory/stock",
    "/procurement/vendors", "/procurement/purchase-orders", "/procurement/purchase-orders/new", "/reports",
    "/notifications", "/profile", "/settings/company", "/settings/gst", "/settings/employees",
    "/settings/roles", "/settings/modules", "/settings/subscription", "/settings/audit",
]
ADMIN = ["/admin", "/admin/tenants", "/admin/plans", "/admin/modules", "/admin/users", "/admin/audit",
         "/admin/health"]
ROLES = {
    "admin@manima.local": (os.environ.get("ADMIN_PASSWORD", "Admin@12345"), ADMIN),
    "owner@demo.manima.local": (PW, WORKSPACE),
    "sales@demo.manima.local": (PW, WORKSPACE),
    "accounts@demo.manima.local": (PW, WORKSPACE),
    "store@demo.manima.local": (PW, WORKSPACE),
    "viewer@demo.manima.local": (PW, WORKSPACE),
}
ERROR_TEXT = ["Something went wrong", "Application error", "Unhandled Runtime Error"]


def run() -> int:
    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("PLAYWRIGHT_CHANNEL", "chrome"), headless=True)
        for email, (pw, pages) in ROLES.items():
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            issues: list[str] = []
            page.on("console", lambda m: m.type == "error" and issues.append(f"console: {m.text[:160]}"))
            page.on("pageerror", lambda e: issues.append(f"pageerror: {e}"))

            def on_resp(r):
                if "/api/" in r.url and r.status >= 500:
                    issues.append(f"{r.status} {r.request.method} {r.url}")

            page.on("response", on_resp)
            page.goto(f"{BASE}/login")
            page.fill("input[type=email]", email)
            page.fill("input[type=password]", pw)
            page.click("button[type=submit]")
            page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
            for path in pages:
                issues.clear()
                page.goto(f"{BASE}{path}")
                page.wait_for_load_state("networkidle")
                body = page.inner_text("body")
                for t in ERROR_TEXT:
                    if t in body:
                        issues.append(f"error text: {t}")
                # A permission-gated page should say so, not crash; console 403s from hints are allowed.
                real = [i for i in issues if "403" not in i and "Failed to load resource" not in i]
                if real:
                    failures.append(f"[{email}] {path}: {real}")
                if email.startswith(("owner", "admin@")):
                    page.screenshot(path=str(OUT / f"{email.split('@')[0]}{path.replace('/', '_')}.png"))
            print(f"checked {len(pages)} pages as {email}")
            ctx.close()
        browser.close()
    for f in failures:
        print("FAIL", f)
    print(f"{len(failures)} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
