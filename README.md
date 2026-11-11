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
2. Copy `.env.example` to `.env` and fill in your own details:
   ```
   LOGIN_URL=...
   GRADES_URL=...
   PORTAL_USERNAME=...
   PORTAL_PASSWORD=...
   ```
3. Adjust the selectors in `.env` if your portal's HTML differs.

## Usage

```
python grades.py          # run headless
python grades.py --show   # watch the browser while it runs
python grades.py --dump   # save the grades page to debug/ for troubleshooting
```

Results are saved to `grades.json`:

```json
[
  {
    "term": "FIRST SEMESTER - 2024",
    "courses": [{ "Course Code": "...", "Description": "...", "Units": "...", "MG": "...", "FG": "..." }],
    "summary": { "Description": "Total Units Passed: ...", "FG": "..." }
  }
]
```

## Privacy and security

- `.env`, `state.json`, and `grades.json` are listed in `.gitignore` and must never be committed.
- This tool is for use on your own computer with your own account only.
- Don't run it against accounts that aren't yours, and don't host it publicly where others would enter their school passwords.
- If the portal adds a CAPTCHA or blocks automated logins, this tool won't work and shouldn't be modified to bypass it.

## Roadmap

- [ ] Frontend to display grades by semester
- [ ] GPA trend chart
- [ ] "What do I need on the final?" calculator
