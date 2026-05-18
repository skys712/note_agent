# Repository Guidelines

## Project Structure & Module Organization

This is a Python CLI project for multi-agent long-form novel writing. Core source code lives in `novel_writer/`.

- `novel_writer/main.py`: CLI entry point and command definitions.
- `novel_writer/core/`: workflow orchestration, context building, LLM client, and logging.
- `novel_writer/agents/`: generated Agent modules plus shared `base.py`.
- `novel_writer/storage/`: Markdown persistence helpers.
- `input_config/`: default world, character, and story constraint inputs.
- `projects/`: local generated writing projects; ignored by Git.
- `world copy/`: local reference material; ignored by Git.

Agent files under `novel_writer/agents/*.py`, except `base.py`, are generated from `setup_agents.py`. Update prompts there, then regenerate.

## Build, Test, and Development Commands

- `python setup_agents.py`: regenerate Agent Python files after editing prompts.
- `python -m novel_writer.main <command>`: run the CLI. Example: `python -m novel_writer.main status`.
- `python -m novel_writer.main init <name> --genre <genre> --logline "<summary>"`: create a writing project.
- `python -m novel_writer.main write section 1 1 1`: run the section writing workflow.

There is no build step. The repository currently has no formal test suite or lint command.

## Coding Style & Naming Conventions

Use Python 3 style with 4-space indentation and type hints where they improve clarity. Keep module and function names in `snake_case`; classes use `PascalCase`.

Terminal/log output should remain ASCII-safe where possible, especially in `novel_writer/core/logging.py`, to avoid Windows GBK encoding failures. User-facing CLI text in this project is Chinese; keep new messages consistent.

Do not bypass `ProjectContext` for project file paths. Add new persistence helpers there instead of hardcoding reads and writes throughout the codebase.

## Testing Guidelines

No test framework is configured yet. For risky changes, add focused tests before introducing broad behavior changes. Prefer `pytest` if a test suite is introduced, with test files named `test_*.py` under a future `tests/` directory.

At minimum, manually verify CLI flows after edits:

```bash
python setup_agents.py
python -m novel_writer.main status
```

## Commit & Pull Request Guidelines

Existing commits use concise Chinese summaries, for example `初始提交: 6 Agent 协作小说创作系统` and `移除临时 prompts 文件`. Follow that style: short, imperative, and specific.

Pull requests should include the purpose, affected commands or workflows, manual verification performed, and screenshots or output snippets only when CLI behavior changes. Note any prompt regeneration and list generated Agent files if they changed.

## Security & Configuration Tips

Do not commit secrets. Required runtime settings come from environment variables: `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`, and `ANTHROPIC_MAX_TOKENS`. Use `NOVEL_WRITER_PROJECTS_DIR` to keep generated projects outside the repository when needed.
