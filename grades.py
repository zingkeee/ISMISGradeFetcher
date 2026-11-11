"""
Personal grade fetcher.
Logs in to your school portal with Playwright, reads the grades table,
and saves it to grades.json. Run it only on your own computer, for your own account.

Usage:
    python grades.py            # headless run
    python grades.py --show     # watch the browser (useful for the first run)
    python grades.py --dump     # save debug/page.html + debug/page.png of the grades page
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

# ---- Settings (all come from .env so you can tune them without editing code) ----
LOGIN_URL = os.environ["LOGIN_URL"]
GRADES_URL = os.environ["GRADES_URL"]
USERNAME = os.environ["PORTAL_USERNAME"]
PASSWORD = os.environ["PORTAL_PASSWORD"]

USERNAME_SELECTOR = os.getenv("USERNAME_SELECTOR", "input[name='username']")
PASSWORD_SELECTOR = os.getenv("PASSWORD_SELECTOR", "input[type='password']")
SUBMIT_SELECTOR = os.getenv("SUBMIT_SELECTOR", "button[type='submit']")
GRADES_TABLE_SELECTOR = os.getenv("GRADES_TABLE_SELECTOR", "table")

STATE_FILE = Path("state.json")   # saved login session (keep private, gitignored)
OUTPUT_FILE = Path("grades.json")  # your grades (keep private, gitignored)
DEBUG_DIR = Path("debug")


def needs_login(page) -> bool:
    """True if the password box is visible, meaning we are on the login page."""
    return page.locator(PASSWORD_SELECTOR).first.is_visible()


def log_in(page):
    page.goto(LOGIN_URL)
    page.fill(USERNAME_SELECTOR, USERNAME)
    page.fill(PASSWORD_SELECTOR, PASSWORD)
    page.click(SUBMIT_SELECTOR)
    page.wait_for_load_state("networkidle")


def read_table(page):
    """Turn the first matching table into a list of dicts keyed by header text."""
    table = page.locator(GRADES_TABLE_SELECTOR).first
    table.wait_for(timeout=15000)

    headers = [h.strip() for h in table.locator("th").all_inner_texts()]
    rows = []
    for tr in table.locator("tr").all():
        cells = [c.strip() for c in tr.locator("td").all_inner_texts()]
        if not cells:
            continue
        if headers and len(headers) == len(cells):
            rows.append(dict(zip(headers, cells)))
        else:
            rows.append({f"col{i + 1}": c for i, c in enumerate(cells)})
    return rows


def main():
    show = "--show" in sys.argv
    dump = "--dump" in sys.argv

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not show)
        context = browser.new_context(
            storage_state=str(STATE_FILE) if STATE_FILE.exists() else None
        )
        page = context.new_page()

        # Try the grades page with the saved session first.
        page.goto(GRADES_URL)
        page.wait_for_load_state("networkidle")

        if needs_login(page):
            print("Logging in...")
            log_in(page)
            page.goto(GRADES_URL)
            page.wait_for_load_state("networkidle")
            if needs_login(page):
                sys.exit("Login failed. Check your username/password and selectors.")
            context.storage_state(path=str(STATE_FILE))  # remember the session
        else:
            print("Reusing saved session.")

        if dump:
            DEBUG_DIR.mkdir(exist_ok=True)
            (DEBUG_DIR / "page.html").write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(DEBUG_DIR / "page.png"), full_page=True)
            print("Saved debug/page.html and debug/page.png")

        grades = read_table(page)
        browser.close()

    OUTPUT_FILE.write_text(json.dumps(grades, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(grades)} rows to {OUTPUT_FILE}")
    for row in grades:
        print(row)


if __name__ == "__main__":
    main()
