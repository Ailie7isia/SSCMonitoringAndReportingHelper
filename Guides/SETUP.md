# Environment Setup Guide

This guide explains how to prepare your computer before running the **SecurityScorecard Portfolio Toolkit**.

---

# Requirements

Install the following software:

* Visual Studio Code (or Cursor)
* Python 3.11 or later
* Git (optional, but recommended)

---

# Step 1 - Install Visual Studio Code

Download Visual Studio Code from the official website:

https://code.visualstudio.com/

Follow the installer and keep the default settings.

Alternatively, if you are using **Cursor**, download it from:

https://www.cursor.com/

---

# Step 2 - Install Python

Download Python from the official website:

https://www.python.org/downloads/

During installation, **make sure to check**:

```
✓ Add Python to PATH
```

This allows Python to be used from the command line.

After installation, verify that Python is installed.

Open **Command Prompt** (Windows) or **Terminal** (macOS/Linux) and run:

```bash
python --version
```

or

```bash
py --version
```

You should see something similar to:

```text
Python 3.13.5
```

---

# Step 3 - Open the Project

Open Visual Studio Code or Cursor.

Select:

```
File
    └── Open Folder
```

Choose the project folder.

---

# Step 4 - Open a Terminal

In VS Code or Cursor:

```
Terminal
    └── New Terminal
```

A terminal window will appear at the bottom.

---

# Step 5 - Install Project Dependencies

Inside the project folder, run:

```bash
pip install -r requirements.txt
```

This installs all Python packages required by the project.

---

# Step 6 - Create the Configuration File

Create a file named:

```
config.yaml
```

Example:

```yaml
securityscorecard:
  api_key: YOUR_API_KEY
  portfolio_id: YOUR_PORTFOLIO_ID
```

Replace the placeholder values with your own SecurityScorecard credentials.

---

# Step 7 - Run the Program

Run:

```bash
python main.py
```

or press the **Run** button while `main.py` is open.

---

# Recommended Beginner Videos

### Visual Studio Code

Visual Studio Code Beginner Tutorial (Programming with Mosh)

https://www.youtube.com/results?search_query=Programming+with+Mosh+VS+Code+tutorial

---

### Python Installation

Python Installation Guide (Corey Schafer)

https://www.youtube.com/results?search_query=Corey+Schafer+Python+installation

---

### Git Basics

Git and GitHub for Beginners (freeCodeCamp)

https://www.youtube.com/results?search_query=freeCodeCamp+Git+and+GitHub+for+Beginners

---

# Verify Everything Works

Run:

```bash
python main.py
```

If the following menu appears, the environment has been set up successfully.

```text
=============================================
 SecurityScorecard Portfolio Toolkit
=============================================

1. Portfolio Cycle
2. Download Reports
3. Export Scores
0. Exit
```

You are now ready to use the application.
