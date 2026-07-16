# Git Quick Guide

This guide covers the basic Git commands used for this project.

---

# First Time Setup

Clone the repository:

```bash
git clone <repository-url>
```

Move into the project folder:

```bash
cd <repository-name>
```

---

# Check Project Status

See which files have changed:

```bash
git status
```

This should be the first command you run before committing changes.

---

# View Changed Files

See what has changed:

```bash
git diff
```

---

# Stage Changes

Stage all modified files:

```bash
git add .
```

Or stage a specific file:

```bash
git add filename.py
```

Staging prepares files to be included in the next commit.

---

# Commit Changes

Create a snapshot of your work:

```bash
git commit -m "Describe your changes"
```

Example:

```bash
git commit -m "Add report download improvements"
```

A commit only saves changes **locally**.

---

# Push Changes

Upload commits to GitHub:

```bash
git push
```

If this is your first push on a new branch:

```bash
git push -u origin main
```

After that, `git push` is sufficient.

---

# Pull Latest Changes

Download the latest changes from GitHub:

```bash
git pull
```

Always pull before starting new work if others may have updated the repository.

---

# Recommended Workflow

The usual workflow is:

```text
Edit files
      ↓
git status
      ↓
git add .
      ↓
git commit -m "Describe changes"
      ↓
git push
```

---

# Ignored Files

Some files should never be committed.

Example `.gitignore`:

```gitignore
__pycache__/
*.pyc

config.yaml
```

These files contain temporary data or sensitive information.

---

# Configuration File

The project expects a local `config.yaml`.

Example:

```yaml
securityscorecard:
  api_key: YOUR_API_KEY
  portfolio_id: YOUR_PORTFOLIO_ID
```

Do **not** commit this file to Git.

---

# Useful Commands

View commit history:

```bash
git log --oneline
```

View remote repository:

```bash
git remote -v
```

Check current branch:

```bash
git branch
```

---

# If You Accidentally Commit Something

## Stop tracking a file

Example:

```bash
git rm --cached config.yaml
```

Then commit the change:

```bash
git commit -m "Stop tracking config file"
git push
```

---

## Remove Python cache files

```bash
git rm -r --cached __pycache__
```

Commit and push afterwards.

---

# Common Problems

### "Nothing to commit"

No files have changed since the last commit.

---

### "Current branch has no upstream branch"

Run:

```bash
git push -u origin main
```

Only required once.

---

### "Merge conflict"

Someone else modified the same file.

Resolve the conflict, save the file, then:

```bash
git add .
git commit
git push
```

---

# Good Practices

* Pull before starting work.
* Commit small, meaningful changes.
* Write clear commit messages.
* Push regularly.
* Never commit API keys or passwords.
* Keep `config.yaml` in `.gitignore`.
* Keep `__pycache__` and `.pyc` files out of Git.

---

# Typical Daily Workflow

```bash
git pull

# Make your changes

git status
git add .
git commit -m "Describe changes"
git push
```

Following this workflow helps keep the repository organized and minimizes merge conflicts.
