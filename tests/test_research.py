"""Tests for research.py — loading text strategy notes from Research/."""
from research import load_research_notes


class TestLoadResearchNotes:
    def test_reads_md_and_txt_with_headers(self, tmp_path):
        (tmp_path / "Brain.md").write_text("# Strategy\nbuy low", encoding="utf-8")
        (tmp_path / "rules.txt").write_text("rule one", encoding="utf-8")
        notes = load_research_notes(str(tmp_path))
        assert "Brain.md" in notes
        assert "buy low" in notes
        assert "rules.txt" in notes
        assert "rule one" in notes

    def test_ignores_images(self, tmp_path):
        (tmp_path / "chart.png").write_bytes(b"\x89PNG fake")
        (tmp_path / "Brain.md").write_text("text here", encoding="utf-8")
        notes = load_research_notes(str(tmp_path))
        assert "chart.png" not in notes
        assert "text here" in notes

    def test_missing_dir_returns_empty(self, tmp_path):
        assert load_research_notes(str(tmp_path / "nope")) == ""

    def test_no_text_files_returns_empty(self, tmp_path):
        (tmp_path / "chart.jpg").write_bytes(b"fake")
        assert load_research_notes(str(tmp_path)) == ""

    def test_truncates_to_max_chars(self, tmp_path):
        (tmp_path / "big.md").write_text("x" * 1000, encoding="utf-8")
        notes = load_research_notes(str(tmp_path), max_chars=200)
        assert len(notes) <= 300  # 200 + header + truncation marker
        assert "truncated" in notes.lower()

    def test_deterministic_filename_order(self, tmp_path):
        (tmp_path / "b.md").write_text("BBB", encoding="utf-8")
        (tmp_path / "a.md").write_text("AAA", encoding="utf-8")
        notes = load_research_notes(str(tmp_path))
        assert notes.index("AAA") < notes.index("BBB")
