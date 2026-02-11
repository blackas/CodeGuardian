"""Tests for diff_parser module."""

from typing import Any

from src.diff_parser import (
    DiffLine,
    parse_patch,
    filter_reviewable_files,
    get_valid_comment_lines,
)


class TestParsePatch:
    """Tests for parse_patch function."""

    def test_parse_single_hunk_patch(self, sample_single_hunk_patch: str):
        """Single hunk: 3 additions + 3 context lines = 6 DiffLines."""
        lines = parse_patch(sample_single_hunk_patch)

        assert len(lines) == 6

        # Line 10: context_line
        assert lines[0].line_number == 10
        assert lines[0].content == "context_line"
        assert lines[0].is_context is True
        assert lines[0].is_addition is False

        # Line 11: +added_line_1
        assert lines[1].line_number == 11
        assert lines[1].content == "added_line_1"
        assert lines[1].is_addition is True

        # Line 12: +added_line_2
        assert lines[2].line_number == 12
        assert lines[2].content == "added_line_2"
        assert lines[2].is_addition is True

        # Line 13: context_line
        assert lines[3].line_number == 13
        assert lines[3].is_context is True

        # Line 14: context_line
        assert lines[4].line_number == 14
        assert lines[4].is_context is True

        # Line 15: +added_line_3
        assert lines[5].line_number == 15
        assert lines[5].content == "added_line_3"
        assert lines[5].is_addition is True

    def test_parse_multi_hunk_patch(self, sample_multi_hunk_patch: str):
        """Multi-hunk: first hunk lines 5-8, second hunk lines 21-23."""
        lines = parse_patch(sample_multi_hunk_patch)

        # First hunk: 3 lines (ctx at 5, +new1 at 6, ctx at 7)
        first_hunk = [line for line in lines if line.line_number <= 10]
        assert len(first_hunk) == 3
        assert first_hunk[0].line_number == 5
        assert first_hunk[0].is_context is True
        assert first_hunk[1].line_number == 6
        assert first_hunk[1].is_addition is True
        assert first_hunk[1].content == "new1"
        assert first_hunk[2].line_number == 7
        assert first_hunk[2].is_context is True

        # Second hunk: 3 lines (ctx at 21, +new2 at 22, +new3 at 23)
        second_hunk = [line for line in lines if line.line_number >= 21]
        assert len(second_hunk) == 3
        assert second_hunk[0].line_number == 21
        assert second_hunk[0].is_context is True
        assert second_hunk[1].line_number == 22
        assert second_hunk[1].is_addition is True
        assert second_hunk[1].content == "new2"
        assert second_hunk[2].line_number == 23
        assert second_hunk[2].is_addition is True
        assert second_hunk[2].content == "new3"

    def test_parse_empty_patch(self):
        """Empty patch returns empty list."""
        assert parse_patch("") == []

    def test_no_newline_at_eof_skipped(self):
        r"""Lines with '\ No newline at end of file' are skipped."""
        patch = "@@ -1,2 +1,2 @@\n-old_line\n+new_line\n\\ No newline at end of file"
        lines = parse_patch(patch)
        # Should only have the +new_line, no DiffLine for the backslash line
        addition_lines = [line for line in lines if line.is_addition]
        assert len(addition_lines) == 1
        assert addition_lines[0].content == "new_line"
        # Verify no line has the backslash content
        for line in lines:
            assert "No newline" not in line.content

    def test_hunk_header_with_function_context(self):
        """Hunk header with function context after @@ is parsed correctly."""
        patch = "@@ -10,3 +10,4 @@ def my_function():\n ctx\n+new_line\n ctx"
        lines = parse_patch(patch)
        assert len(lines) == 3
        assert lines[0].line_number == 10
        assert lines[1].line_number == 11
        assert lines[1].is_addition is True
        assert lines[2].line_number == 12


class TestFilterReviewableFiles:
    """Tests for filter_reviewable_files function."""

    def test_filter_reviewable_files_by_extension(
        self, sample_mixed_files: list[dict[str, Any]]
    ):
        """Only .py, .js, .ts, .html files pass filter."""
        result = filter_reviewable_files(sample_mixed_files)
        filenames = [file["filename"] for file in result]

        assert "src/main.py" in filenames
        assert "src/app.ts" in filenames
        assert "src/index.js" in filenames
        assert "template.html" in filenames
        assert "README.md" not in filenames
        assert "data.csv" not in filenames

    def test_filter_skips_binary_files(self, sample_mixed_files: list[dict[str, Any]]):
        """Binary files (patch=None) are filtered out."""
        result = filter_reviewable_files(sample_mixed_files)
        filenames = [file["filename"] for file in result]

        assert "assets/logo.png" not in filenames

    def test_filter_skips_delete_only_files(
        self, sample_mixed_files: list[dict[str, Any]]
    ):
        """Files with additions=0 (delete-only) are filtered out."""
        result = filter_reviewable_files(sample_mixed_files)
        filenames = [file["filename"] for file in result]

        assert "removed.py" not in filenames


class TestGetValidCommentLines:
    """Tests for get_valid_comment_lines function."""

    def test_get_valid_comment_lines(self, sample_single_hunk_patch: str):
        """Returns all NEW-side line numbers from single hunk."""
        valid_lines = get_valid_comment_lines(sample_single_hunk_patch)

        assert valid_lines == {10, 11, 12, 13, 14, 15}
