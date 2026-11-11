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
from playwright.sync_api import TimeoutError as PWTimeout
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
    """True if we were sent to the login page (expired session) or a password box is showing."""
    if "/account/login" in page.url.lower():
        return True
    return page.locator(PASSWORD_SELECTOR).first.is_visible()


def log_in(page):
    page.goto(LOGIN_URL)
    page.fill(USERNAME_SELECTOR, USERNAME)
    page.fill(PASSWORD_SELECTOR, PASSWORD)
    page.click(SUBMIT_SELECTOR)
    page.wait_for_load_state("networkidle")


# Finds the nearest "... SEMESTER - 2024" style heading above a table.
SEMESTER_JS = """
(table) => {
  const re = /(semester|summer|midyear|trimester)/i;
  let node = table;
  while (node && node !== document.body) {
    let sib = node.previousElementSibling;
    while (sib) {
      if (!sib.querySelector('table') && sib.tagName !== 'TABLE') {
        const lines = (sib.innerText || '').split('\\n')
          .map(s => s.trim()).filter(Boolean).reverse();
        const hit = lines.find(l => re.test(l) && l.length < 80);
        if (hit) return hit;
      }
      sib = sib.previousElementSibling;
    }
    node = node.parentElement;
  }
  return 'Unknown term';
}
"""


def read_all_tables(page):
    """
    Read the grades page.
    Returns {"overall": {...} or None, "terms": [{term, courses, summary}, ...]}.
    Only tables with MG and FG columns count as semester grades; the GWA box
    is captured separately and everything else (footers, curriculum lists) is skipped.
    """
    page.locator(GRADES_TABLE_SELECTOR).first.wait_for(timeout=15000)
    terms, overall = [], None

    for table in page.locator(GRADES_TABLE_SELECTOR).all():
        headers = [h.strip() for h in table.locator("th").all_inner_texts()]
        upper = [h.upper() for h in headers]
        all_text = " ".join(table.all_inner_texts()).lower()

        # Overall GWA box, e.g. "General Weighted Average: 1.75 | Total Units Earned: 117.00"
        if "general weighted average" in all_text:
            cells = [c.strip() for c in table.locator("td").all_inner_texts() if c.strip()]
            overall = {"raw": cells}
            for i, c in enumerate(cells):
                if "weighted average" in c.lower() and i + 1 < len(cells):
                    overall["gwa"] = cells[i + 1]
                if "total units earned" in c.lower():
                    overall["total_units_earned"] = c.split(":")[-1].strip()
            continue

        # Skip anything that is not a semester grades table.
        if "MG" not in upper or "FG" not in upper:
            continue

        term = table.evaluate(SEMESTER_JS)
        courses, summary = [], None
        for tr in table.locator("tr").all():
            cells = [c.strip() for c in tr.locator("td").all_inner_texts()]
            if not cells:
                continue
            row = (
                dict(zip(headers, cells))
                if len(headers) == len(cells)
                else {f"col{i + 1}": c for i, c in enumerate(cells)}
            )
            if not cells[0] and "total units" in " ".join(cells).lower():
                summary = row
            else:
                courses.append(row)
        if courses:
            terms.append({"term": term, "courses": courses, "summary": summary})

    return {"overall": overall, "terms": terms}


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

        try:
            grades = read_all_tables(page)
        except PWTimeout:
            DEBUG_DIR.mkdir(exist_ok=True)
            page.screenshot(path=str(DEBUG_DIR / "timeout.png"), full_page=True)
            STATE_FILE.unlink(missing_ok=True)  # force a fresh login next time
            browser.close()
            sys.exit(
                "Couldn't find the grades table. Saved debug/timeout.png and cleared "
                "the saved session. Run the script again."
            )
        browser.close()

    OUTPUT_FILE.write_text(json.dumps(grades, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(grades['terms'])} semester(s) to {OUTPUT_FILE}")
    if grades["overall"]:
        print("Overall:", grades["overall"])
    for t in grades["terms"]:
        print(f"\n{t['term']}")
        for c in t["courses"]:
            print("  ", c)
        if t["summary"]:
            print("  >>", t["summary"])


if __name__ == "__main__":
    main()