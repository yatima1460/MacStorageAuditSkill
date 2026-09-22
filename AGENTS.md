# Install Mac Storage Audit

Install the Mac Storage Audit skill from https://github.com/yatima1460/MacStorageAuditSkill into the user's Codex skills directory. When the user provides this file or its URL for installation, perform the installation, then explain how to run the skill.

Follow these steps:

1. Download or clone the repository into a temporary directory if it is not already available locally. Read `skills/mac-storage-audit/SKILL.md`. Determine the destination: `$CODEX_HOME/skills` when `CODEX_HOME` is set, otherwise `~/.codex/skills`.
2. Copy **only** `skills/mac-storage-audit` into that directory as `mac-storage-audit`, including `agents`, `scripts`, and `references`. Exclude generated caches such as `__pycache__`. Do not copy repository Git history, tests, or local report/evidence files into the installation.
3. If an installation already exists, inspect it before replacing files. Preserve unrelated skills and local customizations unless updating them is authorized.
4. Verify the installed `SKILL.md`, both helper scripts, `agents/openai.yaml`, and `references/report-input.md` exist. Do not run a disk audit merely to verify installation.
5. **After installation, explain how the user can run it**, using this example:

   ```text
   $mac-storage-audit Scan this Mac and create a detailed HTML storage report.
   ```

   Tell the user it creates a local, responsive `.html` report with system light/dark mode and unreconciled-space accounting. It does not delete files. If the host has not discovered the new skill, suggest starting a new session.

# Repository boundaries

Keep this repository generic. Never commit real scan results, reports, private filesystem paths, device IDs, credentials, or generated Python caches. Use fictional test data. Audit reports belong outside this checkout and must not be published without separate user authorization.

Run helper tests with `python3 -m unittest discover -s tests -v`. Preserve the existing license.
