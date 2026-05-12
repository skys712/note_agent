from pathlib import Path


class MarkdownStore:
    """Markdown 文件读写封装"""

    def __init__(self, root: Path):
        self.root = root

    def read(self, *segments: str) -> str:
        path = self.root.joinpath(*segments)
        return path.read_text("utf-8") if path.exists() else ""

    def write(self, content: str, *segments: str) -> None:
        path = self.root.joinpath(*segments)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def append(self, content: str, *segments: str) -> None:
        path = self.root.joinpath(*segments)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)

    def list_files(self, pattern: str) -> list[Path]:
        return sorted(self.root.glob(pattern))

    def exists(self, *segments: str) -> bool:
        return self.root.joinpath(*segments).exists()
