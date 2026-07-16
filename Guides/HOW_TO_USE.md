# User Guide

This guide explains how to run and use the **SecurityScorecard Portfolio Toolkit**.


---

# Preparation

1. Open the "config_template.yaml" file
2. Complete the data inside
3. Rename the file by deleting the word "_template". File name now should be "config.yaml"
4. Do the same with "constants_template.py"


---

# Opening the Project

1. Open Visual Studio Code (Or your preffered IDE).
2. Select **File → Open Folder**.
3. Open the project folder.
4. Locate **`main.py`** in the project explorer.

---

# Running the Program

1. Open `main.py`.
2. Click the **Run** button (▶) in the top-right corner, **or** open the terminal and run:

```bash
python main.py
```

3. The main menu will appear.

Example:

```text
=============================================
 SecurityScorecard Portfolio Toolkit
=============================================

1. Portfolio Cycle
2. Download Reports
3. Export Scores
0. Exit
```

Enter the number of the function you want to use and press **Enter**.

---

# Menu Options

## 1. Portfolio Cycle

Updates the SecurityScorecard portfolio based on the selected portfolio cycle.

### Steps

1. Select **1** from the main menu.
2. Choose one of the available portfolio cycles.
3. Review the list of companies to be added and removed.
4. Type **YES** to confirm the changes.
5. Wait until the update is complete.
6. A summary of successful and failed operations will be displayed.

> If anything other than **YES** is entered, the operation will be cancelled.

---

## 2. Download Reports

Downloads SecurityScorecard PDF reports for all companies currently in the portfolio.

### Steps

1. Select **2** from the main menu.
2. Wait while the program:

   * Retrieves the portfolio.
   * Checks for existing reports.
   * Generates new reports if necessary.
   * Downloads the reports.
3. Downloaded reports are saved in:

```text
reports/
└── detailed/
    └── YYYY-MM-DD/
```

where `YYYY-MM-DD` is the current date.

---

## 3. Export Scores

Exports the latest SecurityScorecard scores for every company in the portfolio.

### Steps

1. Select **3** from the main menu.
2. The program will:

   * Retrieve the latest company scores.
   * Display the scores in the terminal.
   * Export the data to:

```text
reports/scores.json
```

---

## 0. Exit

Closes the application.

---

# Output Files

| Feature          | Output Location            |
| ---------------- | -------------------------- |
| Download Reports | `reports/detailed/<date>/` |
| Export Scores    | `reports/scores.json`      |

---

# Troubleshooting

### "Configuration file not found"

Ensure `config.yaml` exists in the project folder.

---

### "Missing API key"

Check that `config.yaml` contains a valid SecurityScorecard API key.

---

### "Missing Portfolio ID"

Verify that the Portfolio ID in `config.yaml` is correct.

---

### Program stops unexpectedly

Check the terminal for the error message. Most errors are caused by:

* Incorrect API credentials
* Network connection issues
* SecurityScorecard API errors

---

# Closing the Program

After an operation completes:

1. Press **Enter** to return to the main menu.
2. Select **0** to exit the application.
3. Close the terminal or Cursor when finished.
