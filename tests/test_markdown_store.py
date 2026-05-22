from pathlib import Path

from novel_writer.storage.markdown_store import MarkdownStore


class TestMarkdownStore:
    """MarkdownStore 读写操作测试"""

    def test_write_and_read(self, tmp_dir: Path):
        store = MarkdownStore(tmp_dir)
        store.write("hello world", "test.md")
        assert store.read("test.md") == "hello world"

    def test_read_nonexistent_returns_empty(self, tmp_dir: Path):
        store = MarkdownStore(tmp_dir)
        assert store.read("nonexistent.md") == ""

    def test_write_creates_parent_dirs(self, tmp_dir: Path):
        store = MarkdownStore(tmp_dir)
        store.write("content", "sub", "dir", "file.md")
        assert (tmp_dir / "sub" / "dir" / "file.md").exists()

    def test_exists_true(self, tmp_dir: Path):
        store = MarkdownStore(tmp_dir)
        store.write("data", "exists.md")
        assert store.exists("exists.md")

    def test_exists_false(self, tmp_dir: Path):
        store = MarkdownStore(tmp_dir)
        assert not store.exists("missing.md")

    def test_list_files(self, tmp_dir: Path):
        store = MarkdownStore(tmp_dir)
        store.write("a", "1.md")
        store.write("b", "2.md")
        store.write("c", "3.txt")
        results = store.list_files("*.md")
        names = [p.name for p in results]
        assert "1.md" in names
        assert "2.md" in names
        assert "3.txt" not in names

    def test_list_files_sorted(self, tmp_dir: Path):
        store = MarkdownStore(tmp_dir)
        store.write("z", "z.md")
        store.write("a", "a.md")
        results = store.list_files("*.md")
        names = [p.name for p in results]
        assert names == sorted(names)
