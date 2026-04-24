#!/usr/bin/env python3
"""
Playwright smoke: log into the desk and assert the workspace greeting.

Requires Django runserver (default http://127.0.0.1:8000) and credentials:

  export FAIRDEE_SMOKE_EMAIL=you@example.com
  export FAIRDEE_SMOKE_PASSWORD=secret

Optional: FAIRDEE_BASE_URL (default http://127.0.0.1:8000)
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    note = os.environ.get("FAIRDEE_FLOW_PROMPT", "").strip()
    if note:
        print(f"flow note: {note}")

    base = os.environ.get("FAIRDEE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    email = os.environ.get("FAIRDEE_SMOKE_EMAIL", "").strip()
    password = os.environ.get("FAIRDEE_SMOKE_PASSWORD", "")
    if not email or not password:
        print(
            "Missing FAIRDEE_SMOKE_EMAIL or FAIRDEE_SMOKE_PASSWORD.",
            file=sys.stderr,
        )
        return 2

    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError:
        print("Install deps: pip install -r tools/vibe_server/requirements.txt", file=sys.stderr)
        print("Then: playwright install chromium", file=sys.stderr)
        return 2

    login_url = f"{base}/login/"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(login_url, wait_until="domcontentloaded")
            page.fill('input[name="username"]', email)
            page.fill('input[name="password"]', password)
            page.click('button[type="submit"]')
            page.wait_for_url("**/app/**", timeout=30_000)
            heading = page.locator("h1.desk-page-head__title")
            expect(heading).to_contain_text("Welcome Back", timeout=15_000)
        finally:
            browser.close()

    print("smoke ok: workspace shows Welcome Back")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
