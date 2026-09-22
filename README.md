# Mac Storage Audit

**Quick install:** give your agent this URL and ask it to install the skill:

https://github.com/yatima1460/MacStorageAuditSkill/blob/main/AGENTS.md

A Codex skill that returns a **standalone `.html` report of your Mac's storage**: the largest consumers in an expandable tree, container images, and unreconciled space. Responsive, offline, with automatic system light/dark mode. It does not delete anything.

## Install

Ask Codex:

> Install the skill from https://github.com/yatima1460/MacStorageAuditSkill using the `skills/mac-storage-audit` directory.

Or copy `skills/mac-storage-audit` into `~/.codex/skills/` (or `$CODEX_HOME/skills/`).

## Use

```text
$mac-storage-audit Scan this Mac and create a detailed HTML storage report.
```

Requires macOS and Python 3.9+. Uses as many useful cheap subagents as available, preferring Luna; falls back to the cheapest available model with high effort.

Reports contain local paths—keep them private unless you choose to share them.

[Skill instructions](skills/mac-storage-audit/SKILL.md) · [Report schema](skills/mac-storage-audit/references/report-input.md) · [License](LICENSE)
