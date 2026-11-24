"""Browser workflow test: lead -> invoice draft -> issue -> payment -> dashboard, all through the UI.

Usage: python tests/e2e/workflow.py [base_url]
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)


def login(page: Page, email: str, pw: str) -> None:
    page.goto(f"{BASE}/login")
    page.fill("input[type=email]", email)
    page.fill("input[type=password]", pw)
    page.click("button[type=submit]")
    page.wait_for_url(lambda u: "/login" not in u, timeout=15000)


def pick_first(page: Page, label: str) -> str:
    sel = page.get_by_label(re.compile(f"^{re.escape(label)}")).first
    expect(sel.locator("option").nth(1)).to_be_attached(timeout=10000)
    value = sel.locator("option").nth(1).get_attribute("value")
    sel.select_option(value)
    return value


def dialog_submit(page: Page) -> None:
    page.get_by_role("dialog").get_by_role("button").last.click()


def run() -> None:
    stamp = str(int(time.time()))
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.environ.get("PLAYWRIGHT_CHANNEL", "chrome"), headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        login(page, "owner@demo.manima.local", "Demo@12345")

        # 1. Lead via dialog form
        page.goto(f"{BASE}/crm/leads")
        page.get_by_role("button", name="New lead").click()
        page.get_by_role("dialog").get_by_label(re.compile("^Contact name")).first.fill(f"UI Lead {stamp}")
        dialog_submit(page)
        page.wait_for_url(re.compile(r"/crm/leads/[0-9a-f-]{36}$"), timeout=15000)
        expect(page.locator("h1")).to_have_text(f"UI Lead {stamp}")
        page.goto(f"{BASE}/crm/leads")
        page.get_by_placeholder(re.compile("Search")).fill(f"UI Lead {stamp}")
        expect(page.locator("table").get_by_text(f"UI Lead {stamp}").first).to_be_visible(timeout=10000)
        print("lead created")

        # 2. Draft invoice via document editor
        page.goto(f"{BASE}/billing/invoices/new")
        pick_first(page, "Customer")
        pick_first(page, "Line 1 item")
        page.get_by_label(re.compile("^Line 1 (qty|quantity)", re.I)).fill("2")
        page.get_by_role("button", name="Save draft").click()
        page.wait_for_url(re.compile(r"/billing/invoices/[0-9a-f-]{36}$"), timeout=15000)
        print("draft invoice saved:", page.url)

        # 3. Issue
        page.get_by_role("button", name="Issue invoice").click()
        dialog_submit(page)
        expect(page.get_by_role("button", name="Record payment")).to_be_visible(timeout=10000)
        number = page.locator("h1").inner_text()
        print("issued:", number)

        # 4. Record full payment from the invoice page
        page.get_by_role("button", name="Record payment").click()
        dlg = page.get_by_role("dialog")
        expect(dlg.get_by_label(re.compile("Amount"))).not_to_have_value("", timeout=5000)
        dialog_submit(page)
        expect(page.get_by_role("button", name="Record payment")).to_have_count(0, timeout=10000)
        expect(page.get_by_text(re.compile(r"\bpaid\b", re.I)).first).to_be_visible()
        page.screenshot(path=str(OUT / "workflow_invoice_paid.png"), full_page=True)
        print("payment recorded, invoice paid")

        # 5. Dashboard reflects it
        page.goto(f"{BASE}/dashboard")
        card = page.get_by_text("Invoiced this month").locator("xpath=..")
        expect(card).not_to_contain_text("0 invoices", timeout=10000)
        page.screenshot(path=str(OUT / "workflow_dashboard.png"))
        print("dashboard updated:", card.inner_text().replace("\n", " | "))
        assert not errors, errors
        browser.close()


if __name__ == "__main__":
    run()
    print("WORKFLOW OK")
