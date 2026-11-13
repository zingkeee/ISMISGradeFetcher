"""
Personal grade fetcher.
Logs in to your school portal with Playwright, reads the grades table, and stores private data
under the per-user data directory (outside the project folder by default).

Usage:
    python grades.py            # headless run
    python grades.py --show     # watch the browser (useful for the first run)
    python grades.py --open     # fetch, then open the private grade-book preview
    python grades.py --dump     # save a private page snapshot for troubleshooting
"""
import argparse
import json
import os
import shutil
import webbrowser
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from grade_data import resolve_data_dir, validate_grades_data

APP_DIR = Path(__file__).resolve().parent

# Keep credentials and generated grades out of the project directory by default.
DATA_DIR = resolve_data_dir()
load_dotenv(DATA_DIR / ".env")
STATE_FILE = DATA_DIR / "state.json"
OUTPUT_FILE = DATA_DIR / "grades.json"
WEB_DIR = DATA_DIR / "web"
JS_FILE = WEB_DIR / "grades.js"
DEBUG_DIR = DATA_DIR / "debug"

USERNAME_SELECTOR = os.getenv("USERNAME_SELECTOR", "input[name='username']")
PASSWORD_SELECTOR = os.getenv("PASSWORD_SELECTOR", "input[type='password']")
SUBMIT_SELECTOR = os.getenv("SUBMIT_SELECTOR", "button[type='submit']")
GRADES_TABLE_SELECTOR = os.getenv("GRADES_TABLE_SELECTOR", "table")


def required_settings():
    names = ("LOGIN_URL", "GRADES_URL", "PORTAL_USERNAME", "PORTAL_PASSWORD")
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        raise SystemExit(
            f"Missing setting(s): {', '.join(missing)}. Copy .env.example to {DATA_DIR / '.env'} and configure it."
        )
    return tuple(os.environ[name] for name in names)


def needs_login(page) -> bool:
    """True if we were sent to the login page (expired session) or a password box is showing."""
    if "/account/login" in page.url.lower():
        return True
    return page.locator(PASSWORD_SELECTOR).first.is_visible()


def log_in(page, login_url, username, password):
    page.goto(login_url, wait_until="domcontentloaded")
    page.fill(USERNAME_SELECTOR, username)
    page.fill(PASSWORD_SELECTOR, password)
    page.click(SUBMIT_SELECTOR)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except PWTimeout:
        # Some portals submit asynchronously; needs_login() below verifies outcome.
        pass


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


def prepare_web_bundle(grades):
    """Build a private, self-contained preview beside the private data export."""
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "sw.js", "manifest.webmanifest", "icon-192.png", "icon-512.png"):
        source = APP_DIR / name
        if source.is_file():
            shutil.copy2(source, WEB_DIR / name)
    JS_FILE.write_text(
        "window.GRADES = " + json.dumps(grades, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description="Fetch your own grades from the school portal.")
    parser.add_argument("--show", action="store_true", help="show the browser while it runs")
    parser.add_argument("--dump", action="store_true", help="save a private page snapshot for troubleshooting")
    parser.add_argument("--open", action="store_true", help="open the private grade-book preview after fetching")
    args = parser.parse_args()
    login_url, grades_url, username, password = required_settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.show)
        try:
            context = browser.new_context(
                storage_state=str(STATE_FILE) if STATE_FILE.exists() else None
            )
            page = context.new_page()
            page.goto(grades_url, wait_until="domcontentloaded")

            if needs_login(page):
                print("Logging in...")
                log_in(page, login_url, username, password)
                page.goto(grades_url, wait_until="domcontentloaded")
                if needs_login(page):
                    raise SystemExit("Login failed. Check your username/password and selectors.")
            else:
                print("Reusing saved session.")

            if args.dump:
                DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                (DEBUG_DIR / "page.html").write_text(page.content(), encoding="utf-8")
                page.screenshot(path=str(DEBUG_DIR / "page.png"), full_page=True)
                print(f"Saved private debug snapshot to {DEBUG_DIR}")

            try:
                grades = read_all_tables(page)
            except PWTimeout:
                DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(DEBUG_DIR / "timeout.png"), full_page=True)
                STATE_FILE.unlink(missing_ok=True)
                raise SystemExit(
                    f"Couldn't find the grades table. Saved a private screenshot to {DEBUG_DIR}; "
                    "the saved session was cleared. Run the script again."
                )

            validate_grades_data(grades)
            context.storage_state(path=str(STATE_FILE))
        finally:
            browser.close()

    OUTPUT_FILE.write_text(json.dumps(grades, indent=2, ensure_ascii=False), encoding="utf-8")
    prepare_web_bundle(grades)
    print(f"Saved {len(grades['terms'])} semester(s) to {OUTPUT_FILE}")
    if grades["overall"]:
        print("Overall:", grades["overall"])
    for t in grades["terms"]:
        print(f"\n{t['term']}")
        for c in t["courses"]:
            print("  ", c)
        if t["summary"]:
            print("  >>", t["summary"])

    if args.open:
        webbrowser.open((WEB_DIR / "index.html").resolve().as_uri())


if __name__ == "__main__":
    main()