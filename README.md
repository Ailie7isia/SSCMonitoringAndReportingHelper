# SecurityScorecard Monitoring and Reporting Helper

## Overview

The **SecurityScorecard Monitoring and Reporting Helper** is a Python desktop and command-line application that automates common SecurityScorecard portfolio management tasks.

The toolkit provides three main functions:
* **Portfolio Cycle** – Add and remove companies based on predefined portfolio cycles.
* **Download Reports** – Generate and download fresh Detailed PDF and Issues CSV reports for the active cycle.
* **Update Score History** – Append company scores and grades to an Excel score-history workbook.

The application is designed with a modular structure so that each feature is separated into command, service, and utility layers.

---

## Project Structure

```text
.
├── Commands/
│   ├── portfolio_cycle.py
│   ├── reports_download.py
│   └── scores_export.py
│
├── Services/
│   ├── cycle.py
│   ├── portfolio.py
│   ├── reports.py
│   └── scores.py
│
├── Guides/
├── tests/
│
├── config.py
├── config_template.yaml   (copy to config.yaml)
├── constants_template.py  (copy to constants.py)
├── gui.py
├── main.py
├── models.py
├── ssc_client.py
├── utils.py
└── README.md
```

---

## Requirements

* Python 3.11 or later
* SecurityScorecard API Key
* SecurityScorecard Portfolio ID

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Configuration

Copy **config_template.yaml** to **config.yaml** in the project root and fill
in your credentials. Copy **constants_template.py** to **constants.py** and
fill in the pinned domains and portfolio cycles.

Example:

```yaml
securityscorecard:
  api_key: YOUR_API_KEY
  portfolio_id: YOUR_PORTFOLIO_ID
```

> **Important:**
> Do **not** commit `config.yaml` to source control. It should be included in `.gitignore` because it contains sensitive credentials.

---

## Running the Application

Start the toolkit with:

```bash
python main.py
```

This opens the Windows **SSC Monitoring Helper** dashboard. It presents
portfolio metrics, currently active domains with grade-colored scores, recent
activity, and guided actions for portfolio cycles, report generation, and
append-only Excel score history. Portfolio changes still require an explicit
confirmation.

For the original terminal menu, run:

```bash
python main.py --cli
```

You will be presented with a menu similar to:

```text
=============================================
 SecurityScorecard Portfolio Toolkit
=============================================

1. Portfolio Cycle
2. Download Reports
3. Update Score History
0. Exit
```

Download Reports and Update Score History ask which cycle is being processed.
Each command can also be run directly:

```bash
python Commands/portfolio_cycle.py --option 3 --dry-run
python Commands/reports_download.py --cycle 3
python Commands/scores_export.py --cycle 3
```

Permanently pinned domains are processed with cycle 1 only, so later cycles do
not create duplicate reports or score-history rows.

---

## Features

### 1. Portfolio Cycle

Updates the SecurityScorecard portfolio according to one of the predefined portfolio cycles.

The process:

1. Retrieves the current portfolio.
2. Compares it with the selected cycle.
3. Displays planned additions and removals.
4. Requests confirmation.
5. Applies the changes.
6. Displays a summary.

---

### 2. Download Reports

Generates and downloads fresh Detailed PDF and Issues CSV reports for every
company currently in the portfolio.

The application:

* creates new report requests for the current batch,
* never selects a previous month's report,
* validates downloads, downloading an invalid file again and generating a
  replacement only if it is still invalid,
* saves Detailed PDFs and Issues CSVs into separate date-stamped folders,
* appends the domain to the filename when two companies share a display name.

SecurityScorecard allows 5,000 API requests per rolling hour and applies a
stricter, unpublished limit to Detailed report generation. A limited request
gets HTTP 429 with a `Retry-After` header; nothing reports the remaining
allowance, so the download learns it (see `Services/rate_limit.py`):

* Report requests are sent one at a time, detailed reports at least 3 seconds
  apart.
* After a 429, every request to that endpoint waits out the same cooldown and
  the gap between requests widens; it narrows again after a run of successes.
* If a request is still limited right after waiting, `Retry-After` understated
  the reset, so the wait escalates (1, 2, 5, 10, then 15 minutes). A report is
  only given up on after 65 minutes of waiting for that one request, rather
  than after a fixed number of retries.
* Status checks start every 15 seconds and slow to once a minute.

The **rate-limit timer** in the dashboard sidebar shows, while a download runs,
the countdown to the next request or to the end of a limit, plus how many
requests were sent and how many were limited. A limit hit by any other action
shows a countdown to its reset. Each download ends with a one-line request
summary in the Activity panel.

---

### 3. Update Score History

Retrieves the latest company scores and appends a timestamped record for every
company to the configured Excel score-history workbook.

```text
SSC Helper Log.xlsx
```

Each exported record contains:

* Retrieval time (UTC)
* Domain
* Company name
* SecurityScorecard score
* SecurityScorecard grade
* Cycle

The workbook is stored in the project root by default. To use a different
workbook, set the `SSC_SCORE_HISTORY_PATH` environment variable to its full
`.xlsx` path before starting the app.

---

## Testing

The test suite runs offline against a fake SecurityScorecard client and a
temporary workbook, so it never changes the live portfolio or score history:

```bash
.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

---

## Project Architecture

The project follows a simple layered structure.

| Folder/File     | Responsibility                               |
| --------------- | -------------------------------------------- |
| `Commands/`     | Command-line entry points                    |
| `Services/`     | Business logic and workflows                 |
| `ssc_client.py` | Communication with the SecurityScorecard API |
| `models.py`     | Shared data models                           |
| `utils.py`      | Helper functions                             |
| `config.py`     | Configuration loading and validation         |
| `constants.py`  | Static portfolio configuration               |

---

## Notes for Future Maintenance

* Update `constants.py` when portfolio cycle definitions change.
* Keep `config.yaml` out of version control.
* API requests are centralized in `ssc_client.py`; new API endpoints should be added there.
* Shared business logic should be implemented in the `Services` folder rather than inside command modules.
* Utility functions used across multiple modules should be placed in `utils.py`.

---

## License

This project was developed for internal SecurityScorecard portfolio management and handover purposes.
