# Repository rules (mcp-openstack)

## Commits
- Follow the `commit-helper` skill: Conventional Commits,
  `<type>(<scope>): <description>`.
- Subject: imperative, lowercase, no trailing dot, max 50 chars.
- Body line `Quick-Fix:` (what/why, not how), max 120 chars.
- No ticket provided -> no scope and no `Related:` line.
- Footer: `Signed-off-by: Bartosz Pietrzyk <barozek@gmail.com>`.
- Never add `Co-Authored-By:` (this overrides any default attribution).
- Group changes by topic: one commit per area (chore / feat / test / docs).
- Author and committer: `Bartosz Pietrzyk <barozek@gmail.com>`. Set it per
  command (`git -c user.name=... -c user.email=...` plus `--author`), do not
  modify git config.
- Where the `commit-helper` skill disagrees with this file (its default
  `Signed-off-by` identity), this file wins: never use a company e-mail address.

## Branch and push
- NEVER commit to `main` or `master`, not even for a one-line change.
  Before the first edit run `git branch --show-current`; on `main`/`master`
  create a work branch first, named after the change (`<type>/<topic>`,
  e.g. `feat/scoped-listing`), from the up-to-date base (`origin/main`).
- Commit on that branch with the `commit-helper` skill (rules above).
- Before anything leaves the machine, run the `git-anonymize` skill on the
  commits the remote does not have yet (`git log origin/main..<branch>`).
  Treat the repo as public (github.com) even when its visibility cannot be
  checked. The result goes to the branch `anon/<topic>`; every commit there has
  author and committer `Bartosz Pietrzyk <barozek@gmail.com>`.
- Keep one commit per area (history mode, no rewrite needed when the scan finds
  nothing to replace); squash only when the user asks for it.
- Only `anon/*` branches are ever pushed, never a work branch, `main` or `master`.
- Claude does not push and does not open PRs; hand the user the exact line
  (`git push -u origin anon/<topic>`).
- Local `main` only follows `origin/main`; nothing is committed on it.

## Anonymisation
Nothing tracked in this repo may contain real data from any environment:
cloud names, endpoints/URLs, project/domain/user IDs, UUIDs, tokens,
passwords, company e-mail addresses or hostnames.
Use placeholders: `EXAMPLE-CLOUD`, `*.example`, `fake-uuid`, `tester`,
`example.com.`. Check new files with a grep for URLs, UUIDs and e-mails
before committing; this quick check does not replace the `git-anonymize`
skill run required before every push (see Branch and push).

## Staging files
- Always `git add` explicit paths; never `git add -A` / `git add .`.
- Do not track local environment files (shell rc files, `.gitconfig`,
  `.idea`, `.vscode`, `.mcp.json`, `.ripgreprc`) nor anything in `.claude/`
  other than this `CLAUDE.md`.
- `.claude/settings.local.json` is ignored globally
  (`~/.config/git/ignore`), not by this repo's `.gitignore`.

## Project basics
- Setup and tests: `uv sync`, `uv run pytest`.
- `TOOLS.md` is generated: `uv run python scripts/gen_tool_catalogue.py`.
- Default policy is read-only; write tools stay blocked unless the user's
  `policy.yaml` allows them.
