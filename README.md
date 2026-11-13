# ISMIS Grade Fetcher

A small personal tool that logs in to my university's ISMIS portal and saves my grades to a local JSON file, so I don't have to log in manually every time.

Built with Python and [Playwright](https://playwright.dev/python/).

## Features

- Logs in with a real browser session (handles the portal's CSRF token automatically)
- Saves the login session so later runs can skip the login step
- Reads every semester's grades table and labels each one by term
- Keeps the GPA summary row separate from the course list
- Outputs clean JSON, ready for a frontend

## Setup

1. Install the dependencies:
   ```
   python -m pip install -r requirements.txt
   python -m playwright install chromium
   ```
2. Create the private data directory shown below, copy `.env.example` into it as `.env`, and edit that private copy. Do not put credentials in the OneDrive project folder.
3. Adjust the selectors in the private `.env` if the portal's HTML differs.

## Usage

```sh
python grades.py          # fetch headlessly
python grades.py --show   # watch the browser
python grades.py --dump   # save a private troubleshooting snapshot
python grades.py --open   # open the private preview after fetching
```

Use `python -m unittest discover -s tests -v` to run the local tests. They do not log in to the portal.

## Data and display

Private files are stored outside the project by default: `%LOCALAPPDATA%\GradeFetcher` on Windows, or `$XDG_DATA_HOME/grade-fetcher` / `~/.local/share/grade-fetcher` on macOS/Linux. Set `GRADE_FETCHER_DATA_DIR` to choose another location. The directory contains the saved browser session, grades, local preview, and debug snapshots. `--open` builds and opens the preview there.

The current export is an object with an `overall` summary and a `terms` array:

```json
{
  "overall": { "gwa": "1.75", "total_units_earned": "117.00" },
  "terms": [
    {
      "term": "FIRST SEMESTER - 2024",
      "courses": [{ "Course Code": "...", "Description": "...", "Units": "...", "MG": "...", "FG": "..." }],
      "summary": { "Description": "Total Units Passed: ...", "FG": "..." }
    }
  ]
}
```

The Data tab accepts this format and the older terms-array format. To use it on a phone, transfer `grades.json` using a method you trust and import it. The PWA caches only its app shell, never grade data.

## Privacy and security

- Keep `.env` and the saved browser session private. `state.json` can grant access to your logged-in portal session.
- `.gitignore` prevents generated data from being committed, but **does not prevent OneDrive or another sync service from uploading it**. Keep the credentials file, saved session, grades, and debug snapshots in the private data directory. If old copies already exist inside the synced project folder, move/delete them yourself after confirming the new private location is working. The fetcher does not automatically move or delete existing files.
- Use this only with your own account. Don't host it publicly or ask others to enter school passwords.
- If the portal adds a CAPTCHA or blocks automated logins, don't modify the tool to bypass it.

## Roadmap

- [ ] GPA trend chart
- [ ] “What do I need on the final?” calculator
