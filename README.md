# SecurityScorecard Monitoring and Reporting Helper

## Overview

The **SecurityScorecard Monitoring and Reporting Helper** is a Python command-line application that automates common SecurityScorecard portfolio management tasks.

The toolkit provides three main functions:
* **Portfolio Cycle** – Add and remove companies based on predefined portfolio cycles.
* **Download Reports** – Download the latest SecurityScorecard reports for every company in the portfolio.
* **Export Scores** – Export company scores and grades to a JSON file.

The application is designed with a modular structure so that each feature is separated into command, service, and utility layers.

---

## Project Structure

```text
.
├── Commands/
│   ├── cycle.py
│   ├── reports_download.py
│   └── scores_export.py
│
├── Services/
│   ├── cycle.py
│   ├── portfolio.py
│   ├── reports.py
│   └── scores.py
│
├── config.py
├── constants.py
├── models.py
├── ssc_client.py
├── utils.py
├── main.py
├── config.example.yaml
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

Create a file named **config.yaml** in the project root.

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
3. Export Scores
0. Exit
```

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
* validates downloads and retries an invalid file once,
* saves Detailed PDFs and Issues CSVs into separate date-stamped folders.

---

### 3. Export Scores

Retrieves the latest company scores and appends a timestamped record for every
company to the configured Excel score-history workbook.

```text
SSC Helper Log.xlsx
```

Each exported record contains:

* Company name
* Domain
* SecurityScorecard grade
* SecurityScorecard score

To use a different workbook on another computer, set the
`SSC_SCORE_HISTORY_PATH` environment variable to its full `.xlsx` path before
starting the app.

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
