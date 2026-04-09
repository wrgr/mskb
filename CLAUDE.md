"""Coding assistant behavioral rules applied on every task in this repo."""

# Coding Assistant Guidelines

## Before writing any code

- **Confirm scope first.** Flag and ask before adding files, packages, routes, schema changes, or env vars not explicitly requested.
- If the request is ambiguous, ask one clarifying question rather than assuming.

## While writing code

- Handle all errors explicitly — no empty catch blocks or bare `except: pass`.
- Never hardcode secrets or environment-specific values. Use env vars.
- Keep functions under 60 lines. If growing longer, stop and propose a refactor.
- All new public functions need a type-annotated signature and a one-line docstring.

## Documentation (strictly enforced)

- Every new file gets a module-level docstring: one sentence on what it does and why.
- Non-obvious logic gets an inline comment. If it took thought to write, explain it.
- When you touch an existing file, scan its docstrings and comments. If any are stale, misleading, or no longer match the code, rewrite or remove them in the same pass.
- Never leave `TODO`, `FIXME`, or placeholder comments in non-draft code.
- If you add a dependency, env var, or setup step, update the README in the same pass.

## File length (strictly enforced)

- At 500 lines: flag the file and propose how to split it before proceeding.
- At 1000 lines: hard stop. Refactor before adding anything further.
- New files should do one thing. If "and also…" appears in the docstring, it's two files.

## Dead code (strictly enforced)

- Remove unused imports in every file you touch.
- Delete commented-out code unless you add an explicit note explaining why it's kept.
- If a function, class, or variable is unreferenced, delete it — no "just in case" preservation.

## Before finishing

- Re-read the original request and confirm the code does what was asked.
- List every file changed and why — no silent scope creep.
- All new code has at least a stub test.
