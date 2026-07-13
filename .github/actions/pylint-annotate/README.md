# Pylint Annotate Action

[![GitHub Marketplace](https://img.shields.io/badge/Marketplace-Pylint--Annotate--Action-blue.svg?logo=github)](https://github.com/marketplace)  
⚡ **Annotate your Pull Requests with linting issues detected by [Pylint](https://pylint.pycqa.org/)**

This GitHub Action parses a Pylint JSON report and adds inline annotations to PRs using GitHub Actions workflow commands (`::error`, `::warning`, `::notice`).

**Why use it?**

- See lint warnings & errors directly in the PR “Files Changed” view ✅
- Works on **Node 24** (future standard for GitHub Actions)
- Lightweight — no Docker, runs natively on the runner

---

## 🚀 Usage

### 1. Generate a Pylint JSON report

In your workflow, run Pylint and output JSON:

```bash
pylint --output-format=json . > pylint-report.json || true
```

> `|| true` prevents the step from failing early before annotations are created.

---

### 2. Call this Action in your workflow

```yaml
name: Lint

on:
  pull_request:
    paths:
      - "**.py"

jobs:
  pylint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: 3.11

      - name: Install dependencies
        run: pip install pylint

      - name: Run pylint
        run: pylint --output-format=json . > pylint-report.json || true

      - name: Annotate PR with pylint results
        uses: your-org/pylint-annotate-action@v1
        with:
          file: pylint-report.json
```

---

## 📥 Inputs

| Name   | Required | Description                                                  |
| ------ | -------- | ------------------------------------------------------------ |
| `file` | ✅ Yes   | Path to the Pylint JSON results file (relative to repo root) |

---

## 📝 Example Output in PR

- **Errors** → Red ❌ annotations
- **Warnings** → Yellow ⚠ annotations
- **Notices** → Blue 💡 annotations

Pylint classifications are mapped internally like:

| Pylint Type                      | GitHub Severity |
| -------------------------------- | --------------- |
| `error`, `fatal`                 | ❌ error        |
| `warning`                        | ⚠ warning      |
| `convention`, `refactor`, `info` | 💡 notice       |

---

## 📦 Development

### Install dependencies

```bash
npm install
```

### Build

```bash
npm run build
```

### Test locally

```bash
pylint --output-format=json your_package > pylint-report.json || true
node dist/index.js
```

_(Or run via `npx ts-node src/index.ts` during development)_

---

## ⚡ How It Works

- Reads the Pylint JSON output from the file specified in `file` input.
- Maps each lint message’s severity (`type`) to GitHub’s annotation types.
- Emits workflow commands in the format:

```
::error file=path/to/file.py,line=23,col=5::Some lint error message
```

GitHub Actions automatically turns these into PR annotations.

---

## 📄 License

Cisco proprietary
