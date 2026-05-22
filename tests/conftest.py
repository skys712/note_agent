import tempfile
from pathlib import Path

import pytest

from novel_writer.core.context import ProjectContext


@pytest.fixture
def tmp_dir() -> Path:
    """临时目录，测试结束后自动清理"""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def project_ctx(tmp_dir: Path) -> ProjectContext:
    """初始化好的 ProjectContext 实例"""
    ctx = ProjectContext(tmp_dir / "test_project")
    ctx.init_project_structure({
        "name": "test_project",
        "genre": "奇幻",
        "logline": "一个测试项目",
        "target_volumes": "3",
        "target_chapters_per_volume": "5",
        "target_sections_per_chapter": "3",
    })
    return ctx
