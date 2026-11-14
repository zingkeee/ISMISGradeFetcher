"""
Personal grade fetcher.
Logs in to your school portal with Playwright, reads the grades table, and stores private data
under the per-user data directory (outside the project folder by default).

Usage:
    python grades.py            # headless run
    python grades.py --show     # watch the browser (useful for the first run)
    python grades.py --open     # fetch, then open the private grade-book preview
    python grades.py --dump     # save a private page snapshot for troubleshooting
    python grades.py --force    # overwrite saved grades even if fewer semesters were found
"""
import argparse
import json
import os
import re
import shutil
import time
import webbrowser
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from grade_data import resolve_data_dir, validate_grades_data

APP_DIR = Path(__file__).resolve().parent

# Keep credentials and generated grades out of the project directory by default.
DATA_DIR = resolve_data_dir()
load_dotenv(DATA_DIR / ".env")
STATE_FILE = DATA_DIR / "state.json"
OUTPUT_FILE = DATA_DIR / "grades.json"
PREV_FILE = DATA_DIR / "grades.prev.json"   # the version before the last change
WEB_DIR = DATA_DIR / "web"
JS_FILE = WEB_DIR / "grades.js"
DEBUG_DIR = DATA_DIR / "debug"

# Defaults match ISMIS; override any of them in .env.
USERNAME_SELECTOR = os.getenv("USERNAME_SELECTOR", "#Username")
PASSWORD_SELECTOR = os.getenv("PASSWORD_SELECTOR", "input[type='password']")
SUBMIT_SELECTOR = os.getenv("SUBMIT_SELECTOR", "#loginForm button[type='submit']")
GRADES_TABLE_SELECTOR = os.getenv("GRADES_TABLE_SELECTOR", "table")

DOWN_RE = re.compile(
    r"under maintenance|scheduled maintenance|down for maintenance|temporarily unavailable|service unavailable",
    re.I,
)


class PortalDown(Exception):
    """The portal is offline, erroring, or showing a maintenance page."""


def required_settings():
    names = ("LOGIN_URL", "GRADES_URL", "PORTAL_USERNAME", "PORTAL_PASSWORD")
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        raise SystemExit(
            f"Missing setting(s): {', '.join(missing)}. Copy .env.example to {DATA_DIR / '.env'} and configure it."
        )
    return tuple(os.environ[name] for name in names)


def launch_browser(p, show):
    """Prefer the installed Chrome (the downloaded Chromium can crash on some Windows setups)."""
    attempts = [{"channel": "chrome"}, {}]
    for opts in attempts:
        try:
            return p.chromium.launch(headless=not show, **opts)
        except Exception as e:  # noqa: BLE001 - try the next option
            print(f"Browser start failed ({opts or 'default'}): {str(e).splitlines()[0]}")
    raise SystemExit("Couldn't start a browser. Make sure Google Chrome is installed.")


def needs_login(page) -> bool:
    """True if we were sent to the login page (expired session) or a password box is showing."""
    if "/account/login" in page.url.lower():
        return True
    return page.locator(PASSWORD_SELECTOR).first.is_visible()


def settle(page, timeout=10000):
    """Give the page a moment to finish loading; some portals never go fully idle, which is fine."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except PWTimeout:
        pass


def check_portal(page, response):
    """Raise PortalDown for server errors or a maintenance page (not for a normal login page)."""
    if response is not None and response.status >= 500:
        raise PortalDown(f"The portal returned an error ({response.status}).")
    try:
        if page.locator(PASSWORD_SELECTOR).first.is_visible() or page.locator(GRADES_TABLE_SELECTOR).count():
            return
        text = page.inner_text("body", timeout=5000)
    except PWError:
        return
    if DOWN_RE.search(text[:3000]):
        raise PortalDown("The portal looks like it is under maintenance.")


def goto_checked(page, url, tries=3):
    """Open a URL with a few patient retries, and detect maintenance pages."""
    for attempt in range(1, tries + 1):
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            settle(page)
            check_portal(page, response)
            return
        except PWError:
            if attempt < tries:
                wait = 5 * attempt
                print(f"Couldn't reach the portal (try {attempt}/{tries}). Retrying in {wait}s...")
                time.sleep(wait)
    raise PortalDown("Couldn't reach the portal after several tries. Check your internet or try later.")


def log_in(page, login_url, username, password):
    goto_checked(page, login_url)
    page.fill(USERNAME_SELECTOR, username)
    page.fill(PASSWORD_SELECTOR, password)
    page.click(SUBMIT_SELECTOR)
    settle(page, 15000)  # needs_login() afterwards verifies the outcome


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


def write_atomic(path: Path, text: str):
    """Write via a temp file so a crash can never leave a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save_grades(grades, force=False):
    """Save results safely: never replace good data with empty or shrunken data."""
    if not grades["terms"]:
        raise SystemExit("Found no semesters on the page, so your saved grades were left unchanged.")

    new_json = json.dumps(grades, indent=2, ensure_ascii=False)
    if OUTPUT_FILE.exists():
        old = OUTPUT_FILE.read_text(encoding="utf-8")
        try:
            old_count = len(json.loads(old).get("terms", []))
        except (ValueError, AttributeError):
            old_count = 0
        if len(grades["terms"]) < old_count and not force:
            raise SystemExit(
                f"Found {len(grades['terms'])} semesters but your saved file has {old_count}. "
                "The page may not have loaded fully, so nothing was overwritten. "
                "Run again, or use --force if this is correct."
            )
        if old == new_json:
            print("No changes since the last fetch.")
        else:
            write_atomic(PREV_FILE, old)  # keep the previous version
    write_atomic(OUTPUT_FILE, new_json)


def prepare_web_bundle(grades):
    """Build a private, self-contained preview beside the private data export."""
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "sw.js", "manifest.webmanifest", "icon-192.png", "icon-512.png"):
        source = APP_DIR / name
        if source.is_file():
            shutil.copy2(source, WEB_DIR / name)
    write_atomic(JS_FILE, "window.GRADES = " + json.dumps(grades, ensure_ascii=False) + ";\n")


def fetch(browser, login_url, grades_url, username, password, dump):
    context = browser.new_context(storage_state=str(STATE_FILE) if STATE_FILE.exists() else None)
    page = context.new_page()
    goto_checked(page, grades_url)  # try the saved session first

    if needs_login(page):
        print("Logging in...")
        log_in(page, login_url, username, password)
        goto_checked(page, grades_url)
        if needs_login(page):
            STATE_FILE.unlink(missing_ok=True)
            raise SystemExit(
                "Login failed. Check your username/password and selectors. Your saved grades are unchanged."
            )
    else:
        print("Reusing saved session.")

    if dump:
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
            "the saved session was cleared. Run the script again. Your saved grades are unchanged."
        )

    validate_grades_data(grades)
    context.storage_state(path=str(STATE_FILE))
    return grades


def main():
    parser = argparse.ArgumentParser(description="Fetch your own grades from the school portal.")
    parser.add_argument("--show", action="store_true", help="show the browser while it runs")
    parser.add_argument("--dump", action="store_true", help="save a private page snapshot for troubleshooting")
    parser.add_argument("--open", action="store_true", help="open the private grade-book preview after fetching")
    parser.add_argument("--force", action="store_true", help="overwrite saved grades even if fewer semesters were found")
    args = parser.parse_args()
    login_url, grades_url, username, password = required_settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = launch_browser(p, args.show)
            try:
                grades = fetch(browser, login_url, grades_url, username, password, args.dump)
            finally:
                browser.close()
    except PortalDown as e:
        raise SystemExit(f"{e} Your saved grades are unchanged. Try again later.")

    save_grades(grades, args.force)
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