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

## Branch and push
- Commits go straight to `main`.
- Claude does not push; hand the user the exact command instead
  (`git push origin main`).

## Anonymisation
Nothing tracked in this repo may contain real data from any environment:
cloud names, endpoints/URLs, project/domain/user IDs, UUIDs, tokens,
passwords, company e-mail addresses or hostnames.
Use placeholders: `EXAMPLE-CLOUD`, `*.example`, `fake-uuid`, `tester`,
`example.com.`. Check new files with a grep for URLs, UUIDs and e-mails
before committing.

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
