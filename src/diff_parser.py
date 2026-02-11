"""Unified diff parser with line mapping for code review comments."""

import re
from dataclasses import dataclass
from typing import Any

HUNK_HEADER_PATTERN = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

REVIEWABLE_EXTENSIONS = frozenset({".py", ".js", ".ts", ".html"})


@dataclass
class DiffLine:
    """A single line from a unified diff with its NEW-file line number.

    Attributes:
        line_number: Line number in the NEW file.
        content: Line content without the diff prefix (+, -, space).
        is_addition: True if line was added (+).
        is_deletion: True if line was deleted (-).
        is_context: True if line is unchanged context (space).
    """

    line_number: int
    content: str
    is_addition: bool
    is_deletion: bool
    is_context: bool


def parse_patch(patch: str) -> list[DiffLine]:
    """Parse a unified diff patch string into a list of DiffLine objects.

    Handles multiple hunks, skips deletion-only lines (they have no
    NEW-file line number), and ignores '\\ No newline at end of file'.

    Args:
        patch: Unified diff patch string. May be empty.

    Returns:
        List of DiffLine objects for context and addition lines.
        Deletion lines are excluded (no NEW-file line number).
    """
    if not patch:
        return []

    result: list[DiffLine] = []
    current_new_line = 0

    for raw_line in patch.split("\n"):
        # Skip "\ No newline at end of file"
        if raw_line.startswith("\\"):
            continue

        # Check for hunk header
        header_match = HUNK_HEADER_PATTERN.match(raw_line)
        if header_match:
            current_new_line = int(header_match.group(3))
            continue

        if not raw_line:
            continue

        prefix = raw_line[0]
        content = raw_line[1:]

        if prefix == "+":
            result.append(
                DiffLine(
                    line_number=current_new_line,
                    content=content,
                    is_addition=True,
                    is_deletion=False,
                    is_context=False,
                )
            )
            current_new_line += 1
        elif prefix == "-":
            # Deletion lines don't get a NEW-file line number; skip them
            continue
        elif prefix == " ":
            result.append(
                DiffLine(
                    line_number=current_new_line,
                    content=content,
                    is_addition=False,
                    is_deletion=False,
                    is_context=True,
                )
            )
            current_new_line += 1

    return result


def filter_reviewable_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter files to only those worth reviewing.

    Keeps files that:
    - Have a reviewable extension (.py, .js, .ts, .html)
    - Have a non-None patch (not binary)
    - Have at least one addition (not delete-only)

    Args:
        files: List of file dicts with keys: filename, patch, additions, deletions.

    Returns:
        Filtered list of file dicts.
    """
    result: list[dict[str, Any]] = []

    for file in files:
        filename = file.get("filename", "")
        patch = file.get("patch")
        additions = file.get("additions", 0)

        # Skip binary files (no patch)
        if patch is None:
            continue

        # Skip delete-only files
        if additions == 0:
            continue

        # Check extension
        dot_index = filename.rfind(".")
        if dot_index == -1:
            continue

        extension = filename[dot_index:]
        if extension not in REVIEWABLE_EXTENSIONS:
            continue

        result.append(file)

    return result


def get_valid_comment_lines(patch: str) -> set[int]:
    """Get NEW-file line numbers where review comments can be posted.

    GitHub only allows comments on lines visible in the diff.
    This returns all NEW-side line numbers (both additions and context).

    Args:
        patch: Unified diff patch string.

    Returns:
        Set of valid line numbers for posting comments.
    """
    diff_lines = parse_patch(patch)
    return {line.line_number for line in diff_lines}
