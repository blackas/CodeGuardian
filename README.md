# CodeGuardian

AI code reviewer that automatically reviews Pull Requests (GitHub) and Merge Requests (GitLab). Uses OpenAI GPT-4o-mini to detect bugs, security vulnerabilities, and performance issues — with context-aware review tailored to your project.

## Features

- **Dual Platform** — Works on both GitHub Actions and GitLab CI/CD
- **Auto-Detection** — Automatically detects which CI environment is running
- **Inline Comments** — Posts review comments directly on specific lines of code
- **Context-Aware Review** — Reads `AGENTS.md` from your repository to understand project structure, architecture, and domain-specific concerns. Tailors review focus to your project's needs.
- **Fork-Safe** — Detects fork PRs and exits early to avoid leaking secrets
- **Hallucination Guard** — Validates AI-suggested line numbers against the actual diff

## Project Context (AGENTS.md)

CodeGuardian reads `AGENTS.md` from the base branch (e.g., `main`) of your repository to understand your project's structure, architecture, and domain-specific concerns. This context is used to build a project-specific review prompt that tailors CodeGuardian's focus to your needs.

**How it works:**
1. When a PR/MR is opened, CodeGuardian fetches `AGENTS.md` from the base branch
2. The content is parsed and included in the review prompt sent to GPT-4o-mini
3. The AI reviewer uses this context to identify issues relevant to your project
4. If no `AGENTS.md` exists, CodeGuardian falls back to a generic senior developer review

**Example AGENTS.md:**

```markdown
# Project Context

## Architecture
- Microservices with async/await patterns
- PostgreSQL with connection pooling
- Redis for caching

## Key Concerns
- Race conditions in concurrent operations
- N+1 query problems
- Memory leaks in long-running processes
- Timezone handling in timestamps

## Code Standards
- Type hints required (mypy strict mode)
- 100% test coverage for critical paths
- No hardcoded credentials
```

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

- [uv](https://docs.astral.sh/uv/) (Python package manager)
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
      - uses: astral-sh/setup-uv@v5
        with:
          version: "latest"
      - run: uv run python -m src.review
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

**3. Copy the `src/` directory and `pyproject.toml` into your repo.**

**4. Open a PR — CodeGuardian will automatically review it.**

### 다른 Repository에서 사용하기 (Reusable Workflow)

여러 개의 Repository에서 CodeGuardian을 사용하려면, **Reusable Workflow**를 사용하는 것이 가장 간단합니다. 이 방식은 CodeGuardian 소스 코드를 복사할 필요 없이, 중앙 Repository의 workflow를 재사용합니다.

**장점:**
- 소스 코드 복사 불필요
- 중앙 Repository에서 한 번만 업데이트하면 모든 Repository에 적용
- 각 Repository는 최소한의 설정만 필요

**1. 대상 Repository에 OpenAI API Key를 Secret으로 등록:**

Settings → Secrets and variables → Actions → New repository secret

| Name | Value |
|------|-------|
| `OPENAI_API_KEY` | `sk-...` |

**2. 대상 Repository에 `.github/workflows/codeguardian.yml` 파일 생성:**

```yaml
name: CodeGuardian Review
on:
  pull_request:
    types: [opened, synchronize]

jobs:
  review:
    uses: blackas/CodeGuardian/.github/workflows/reusable-review.yml@main
    permissions:
      contents: read
      pull-requests: write
    secrets:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

**3. (선택) 대상 Repository에 `AGENTS.md` 파일 추가:**

프로젝트의 아키텍처, 주요 관심사, 코드 표준을 정의하는 `AGENTS.md` 파일을 Repository 루트에 추가하면, CodeGuardian이 프로젝트에 맞춘 더 정확한 리뷰를 수행합니다. (자세한 내용은 [Project Context (AGENTS.md)](#project-context-agentsmd) 섹션 참고)

**4. PR을 열면 CodeGuardian이 자동으로 리뷰합니다.**

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
  before_script:
    - pip install uv
  script:
    - uv run python -m src.review
  variables:
    GITLAB_TOKEN: $GITLAB_TOKEN
    OPENAI_API_KEY: $OPENAI_API_KEY
```

**4. Copy the `src/` directory and `pyproject.toml` into your repo.**

**5. Open a Merge Request — CodeGuardian will automatically review it.**

## Local Development

### Install dependencies

```bash
uv sync --group dev
```

### Run tests

```bash
uv run pytest tests/ -v
```

### Dry run (mock mode)

GitHub mode:

```bash
GITHUB_EVENT_PATH=tests/fixtures/event.json \
OPENAI_API_KEY=mock \
GITHUB_TOKEN=mock \
uv run python -m src.review
```

GitLab mode:

```bash
CI_MERGE_REQUEST_IID=42 \
CI_PROJECT_ID=1 \
OPENAI_API_KEY=mock \
GITLAB_TOKEN=mock \
uv run python -m src.review
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
Read AGENTS.md from base branch
    │
    ▼
Fetch changed files
    │
    ▼
Filter: .py, .js, .ts, .html only
    │
    ▼
Send diffs + context to GPT-4o-mini
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

Managed via [uv](https://docs.astral.sh/uv/) with `pyproject.toml`.

| Package | Version | Purpose |
|---------|---------|---------|
| PyGithub | >=2.5.0 | GitHub API client |
| python-gitlab | >=4.13.0 | GitLab API client |
| openai | >=1.58.0 | OpenAI GPT-4o-mini |
| pydantic | >=2.10.0 | Structured output models |

Dev dependencies: `pytest`, `pytest-mock`

## License

MIT
