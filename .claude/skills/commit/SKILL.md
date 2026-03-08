---
name: commit
description: Lint, format, then commit staged and unstaged changes with a conventional commit message.
argument-hint: "[message]"
---

Create a git commit for this project. Follow these steps in order:

## 1. Check lint and format

Run `uv run ruff check && uv run ruff format --check`.

If either fails:
- Run `uv run ruff format` to fix formatting automatically.
- Run `uv run ruff check --fix` to fix auto-fixable lint errors.
- If lint errors remain that cannot be auto-fixed, report them and stop — do not commit broken code.

## 2. Review what will be committed

Run `git status` and `git diff` (staged and unstaged) to understand the full set of changes.

## 3. Stage files

Stage all modified tracked files. Do not stage:
- `.env` files or anything containing secrets
- Files unrelated to the current task
- Large binary files not already tracked

## 4. Write the commit message

If `$ARGUMENTS` was provided, use it as the commit message subject (still apply the format below).

Otherwise, derive the message from the diff. Use conventional commits format:

```
<type>: <short imperative summary>

[optional body — include if the why is not obvious from the summary]
```

Types: `feat` `fix` `refactor` `test` `docs` `chore` `style`

Rules:
- Subject line ≤ 72 characters, lowercase, imperative mood, no full stop
- If the change touches a BDD feature file, mention it in the body
- If it is a non-breaking API change, note it
- Do not pad with filler like "this commit..."

## 5. Commit

```
git commit -m "..."
```

Then run `git status` to confirm the working tree is clean.
