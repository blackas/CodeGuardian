# CodeGuardian

AI code reviewer that automatically reviews Pull Requests (GitHub) and Merge Requests (GitLab). Uses OpenAI GPT-4o-mini to detect bugs, security vulnerabilities, and performance issues — with special awareness for **Quant Trading** patterns.

## Features

- **Dual Platform** — Works on both GitHub Actions and GitLab CI/CD
- **Auto-Detection** — Automatically detects which CI environment is running
- **Inline Comments** — Posts review comments directly on specific lines of code
- **Quant Trading Focus** — Extra-critical about:
  - `float == float` comparisons (suggests `math.isclose()` or `Decimal`)
  - `float` for monetary/price calculations (suggests `Decimal`)
  - Timezone-naive `datetime` in trading logic
  - O(n²) loops in order matching / signal processing
  - Race conditions in async order execution
  - Missing error handling around exchange API calls
- **Fork-Safe** — Detects fork PRs and exits early to avoid leaking secrets
- **Hallucination Guard** — Validates AI-suggested line numbers against the actual diff

## Architecture

```
src/
├── platform_protocol.py   # CodeReviewPlatform Protocol + shared types
├── diff_parser.py          # Unified diff parsing and line mapping
├── ai_reviewer.py          # OpenAI GPT-4o-mini structured output
├── github_client.py        # GitHub API (PyGithub)
├── gitlab_client.py        # GitLab API (python-gitlab)
└── review.py               # Main orchestrator + auto-detection
```

## Setup

### Prerequisites

- Python 3.11+
- OpenAI API Key ([platform.openai.com](https://platform.openai.com))

### GitHub Actions

**1. Add the OpenAI API key as a repository secret:**

Settings → Secrets and variables → Actions → New repository secret

| Name | Value |
|------|-------|
| `OPENAI_API_KEY` | `sk-...` |

> `GITHUB_TOKEN` is automatically provided by GitHub Actions.

**2. Copy the workflow file into your repository:**

```bash
mkdir -p .github/workflows
cp .github/workflows/codeguardian.yml <your-repo>/.github/workflows/
```

Or create `.github/workflows/codeguardian.yml`:

```yaml
name: CodeGuardian Review
on:
  pull_request:
    types: [opened, synchronize]

permissions:
  contents: read
  pull-requests: write

concurrency:
  group: codeguardian-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python -m src.review
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

**3. Copy the `src/` directory and `requirements.txt` into your repo.**

**4. Open a PR — CodeGuardian will automatically review it.**

### GitLab CI/CD

**1. Create a Project Access Token:**

Settings → Access Tokens → Add new token

| Setting | Value |
|---------|-------|
| Role | Developer (or higher) |
| Scopes | `api` |

> `CI_JOB_TOKEN` does **not** have permission to post MR comments. You must use a Project Access Token.

**2. Add CI/CD variables:**

Settings → CI/CD → Variables

| Name | Value | Options |
|------|-------|---------|
| `GITLAB_TOKEN` | `glpat-...` | Masked |
| `OPENAI_API_KEY` | `sk-...` | Masked |

**3. Copy `.gitlab-ci.yml` into your repository root:**

```yaml
codeguardian-review:
  image: python:3.11-slim
  stage: test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
  script:
    - pip install -r requirements.txt
    - python -m src.review
  variables:
    GITLAB_TOKEN: $GITLAB_TOKEN
    OPENAI_API_KEY: $OPENAI_API_KEY
```

**4. Copy the `src/` directory and `requirements.txt` into your repo.**

**5. Open a Merge Request — CodeGuardian will automatically review it.**

## Local Development

### Install dependencies

```bash
pip install -r requirements.txt
pip install pytest pytest-mock
```

### Run tests

```bash
python -m pytest tests/ -v
```

### Dry run (mock mode)

GitHub mode:

```bash
GITHUB_EVENT_PATH=tests/fixtures/event.json \
OPENAI_API_KEY=mock \
GITHUB_TOKEN=mock \
python -m src.review
```

GitLab mode:

```bash
CI_MERGE_REQUEST_IID=42 \
CI_PROJECT_ID=1 \
OPENAI_API_KEY=mock \
GITLAB_TOKEN=mock \
python -m src.review
```

> When `OPENAI_API_KEY` is set to `mock`, CodeGuardian returns canned responses without calling the OpenAI API.

## How It Works

```
PR/MR Opened
    │
    ▼
Auto-detect platform (GitHub or GitLab)
    │
    ▼
Fork PR? ──yes──▶ Exit (no API calls)
    │
    no
    ▼
Fetch changed files
    │
    ▼
Filter: .py, .js, .ts, .html only
    │
    ▼
Send diffs to GPT-4o-mini
    │
    ▼
Validate line numbers against diff
    │
    ▼
Post inline comments + summary
```

## Reviewed File Types

Only files with the following extensions are reviewed:

- `.py` (Python)
- `.js` (JavaScript)
- `.ts` (TypeScript)
- `.html` (HTML)

Binary files, markdown, and config files are skipped.

## Environment Variables

### GitHub Actions

| Variable | Source | Description |
|----------|--------|-------------|
| `GITHUB_TOKEN` | Automatic | GitHub token with PR write access |
| `GITHUB_EVENT_PATH` | Automatic | Path to webhook event JSON |
| `OPENAI_API_KEY` | Secret | OpenAI API key |

### GitLab CI/CD

| Variable | Source | Description |
|----------|--------|-------------|
| `CI_MERGE_REQUEST_IID` | Automatic | MR number |
| `CI_PROJECT_ID` | Automatic | GitLab project ID |
| `CI_SERVER_URL` | Automatic | GitLab instance URL |
| `GITLAB_TOKEN` | CI Variable | Project Access Token |
| `OPENAI_API_KEY` | CI Variable | OpenAI API key |

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| PyGithub | 2.5.0 | GitHub API client |
| python-gitlab | 4.13.0 | GitLab API client |
| openai | 1.58.0 | OpenAI GPT-4o-mini |
| pydantic | 2.10.0 | Structured output models |

## License

MIT
