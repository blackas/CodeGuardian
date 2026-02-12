# CodeGuardian

GitHub PR / GitLab MR이 열리면 자동으로 AI 코드 리뷰를 수행하는 GitHub Action / GitLab CI 파이프라인.

## Tech Stack

- Python 3.11+, uv (패키지 매니저)
- OpenAI GPT-4o-mini (structured JSON output)
- PyGithub, python-gitlab
- Pydantic (응답 스키마), pytest

## Architecture

```
review.py (orchestrator)
  ├─ create_platform()        → env 기반 GitHub/GitLab 자동 감지
  ├─ _fetch_project_context() → base branch에서 AGENTS.md 읽기
  ├─ AIReviewer               → GPT-4o-mini로 diff 리뷰
  └─ validate_comment_lines() → AI 응답의 line number를 diff 기준으로 검증
```

| Module | Role |
|--------|------|
| `platform_protocol.py` | `CodeReviewPlatform` Protocol (duck typing) + `PlatformContext`, `PlatformFile` dataclass |
| `github_client.py` | PyGithub 기반 PR API 클라이언트. `create_review()` batch → 422 시 individual fallback |
| `gitlab_client.py` | python-gitlab 기반 MR API 클라이언트. `discussions.create()` inline comment |
| `ai_reviewer.py` | OpenAI API 호출 + structured output 파싱. `project_context` 기반 동적 시스템 프롬프트 |
| `diff_parser.py` | unified diff 파싱, reviewable 파일 필터링 (.py/.js/.ts/.html), valid line set 추출 |
| `review.py` | 메인 오케스트레이터. platform 감지 → context fetch → diff → AI review → post comments |

## Key Design Decisions

- **Protocol 기반 추상화**: `typing.Protocol` 사용 (상속 없음, duck typing)
- **Base branch에서 AGENTS.md fetch**: PR branch가 아닌 base branch에서 읽음 (prompt injection 방지)
- **AGENTS.md 없으면 generic prompt**: bug/security/performance/readability 포커스
- **Comment format**: `{path, body, line}` dict → 각 클라이언트가 플랫폼 API 형식으로 변환
- **GitHub inline comment**: `create_review(event="COMMENT")` + `line` + `side="RIGHT"`. 30개씩 batch
- **GitLab inline comment**: `mr.discussions.create()` with position object (`base_sha`, `head_sha`, `new_line`)
- **Mock mode**: `OPENAI_API_KEY="mock"` → API 호출 없이 canned response 반환
- **Fork PR 차단**: fork에서 온 PR은 secret 보호를 위해 리뷰 skip

## Pipeline Flow

1. CI 환경 자동 감지 (`GITHUB_EVENT_PATH` or `CI_MERGE_REQUEST_IID`)
2. PR/MR context 수집 (title, description, head_sha)
3. Base branch에서 `AGENTS.md` fetch → project_context
4. Fork PR 체크 → fork면 exit
5. Changed files fetch → `.py/.js/.ts/.html`만 필터
6. `AIReviewer.review_files()` → GPT-4o-mini structured JSON output
7. `validate_comment_lines()` → AI가 제안한 line이 실제 diff에 있는지 검증
8. Platform API로 inline comment + summary 게시

## Conventions

- Type hints 사용 (Literal, Protocol, dataclass)
- docstring: Google style (Args, Returns, Raises)
- 테스트: pytest + pytest-mock, 75 tests
- 에러 처리: 각 클라이언트에서 platform-specific exception catch → WARNING log → graceful degradation

## Cross-Repo Usage

다른 repo에서 reusable workflow로 사용 가능:
```yaml
uses: blackas/CodeGuardian/.github/workflows/reusable-review.yml@main
secrets:
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```
