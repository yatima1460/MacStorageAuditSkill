---
name: mac-storage-audit
description: Analyze Mac disk usage with many inexpensive subagents and a responsive HTML tree report, including unreconciled space. Use for disk usage investigations and identifying cleanup candidates; analysis does not authorize deletion.
---

# Mac Storage Audit

Produce a measured ranking of the largest local storage consumers, explain their purpose where identifiable, and distinguish usage from potentially reclaimable space. Keep the audit read-only apart from temporary evidence files. Do not delete, prune, uninstall, hydrate cloud files, start virtual machines or simulators, or change privacy settings as part of analysis.

## Keep the skill generic

Keep this skill and all bundled resources machine-independent. Do not embed usernames, home-directory literals, project names, device identifiers, private image references, scan results, timestamps from actual runs, or links to a user's evidence files. Discover names and paths at runtime. Store machine-specific inventories, reports, and timing comparisons only in the run's evidence directory, never inside the skill. Examples must use placeholders or standard macOS paths. User-specific retention choices belong to the current task, not to reusable skill rules.

## Establish scope and accounting

Use the current home directory and live mount layout rather than remembered sizes or paths. Default to the internal startup disk; inventory external volumes separately and scan them only when requested. Capture `df -k`, `diskutil apfs list`, and `mount` to establish filesystem capacity, APFS sharing, and mounted images. When snapshots could explain a gap, inspect `tmutil listlocalsnapshots /` and the relevant volume's snapshot listing without modifying snapshots.

If `diskutil` cannot access DiskManagement inside the sandbox, use one permitted read-only execution outside it before concluding the framework is unavailable. This does not require sudo or changing privacy settings. For mounted disk images, `hdiutil info` maps mount points to backing files; count only the backing allocation on the internal disk.

Partition existing paths into disjoint scan roots before dispatch. Cover hidden home directories as well as visible ones, applications, shared libraries, package stores, and private data. Build the explicit root/exclusion manifest before launching scans; apply exclusions before invoking the helper, not merely when formatting the report. Record whether each cloud-managed root received immediate metadata only, a bounded recursive allocation scan, or no scan; never describe recursive `du` as an immediate-only inventory. Typical partitions:

- Home children except Library: projects, Downloads, media, hidden caches and model stores.
- Home Library children: Application Support, Developer, Containers, Group Containers, Caches, and other existing children.
- Outside home: `/Applications`, `/Library`, `/opt`, `/usr/local`, `/private/var`, `/private/tmp`, and other users where readable.

These are discovery hints, not a fixed exhaustive list. Account for unassigned paths. Do not assign both a parent and its descendants to simultaneous recursive scans. Do not count `/System/Volumes/Data` and its firmlinked paths twice. Mounted simulator images, external volumes, and network filesystems need separate accounting.

## Maximize inexpensive parallel delegation

**Strongly prefer maximum useful fan-out: spawn as many cheap subagents as the current environment permits and the independent work can use. Fill available subagent slots rather than defaulting to a small fixed worker count.** Give every worker a concrete, nonoverlapping assignment. Keep the coordinator responsible for accounting, verification, and synthesis. Reuse idle workers for remaining inventory, naming, metadata, coverage analysis, and report checks; do not create duplicate scans merely to occupy slots.

Prefer **Luna with high reasoning effort**. When exposed by the environment, use `model: "gpt-5.6-luna"`, `reasoning_effort: "high"`, and an isolated task context such as `fork_turns: "none"`. If Luna is unavailable, use **the cheapest currently available subagent model with high effort**, based on the environment's current model availability and cost metadata. Do not bake in a permanent fallback model ranking. If cost information is absent, consult the runtime's documented model catalog/pricing if accessible; otherwise disclose that the cheapest option could not be verified and select the lowest-cost option supported by available evidence. Report the selected model and any limitation. Do not pretend an unavailable high-effort setting was applied.

Use the delegation API actually exposed by the host; tool names and argument spelling can vary. Respect its concurrency limit and reserve the coordinator's slot. A large worker pool does not require every worker to traverse the disk simultaneously: keep each worker to one recursive scan at a time and coordinate disk scans to avoid I/O thrashing. Other workers can inspect saved metadata or prepare report sections while scan slots are busy. Adjust active scan concurrency using measured throughput, not an arbitrary cap on the total number of useful cheap workers. Keep the coordinator in charge of dispatch so nested spawning cannot duplicate roots or exceed the host limit.

Each assignment must include:

- Exact absolute roots, exclusions, internal-volume boundary, and read-only scope.
- Capture an allocated-size inventory with enough saved depth for the requested tree, then drill only where needed; include hidden entries. Use macOS tools, typically `/usr/bin/du -k -x -d 2 '/absolute/root'`, retaining stderr and exit status separately from sortable numeric output. Depth limits output, not traversal cost.
- Return structured rows with absolute path, immediate parent path, allocated KiB or null, label, measurement kind, and completion status, plus scan timestamps, commands, and evidence locations. Include the largest children of each leading category, not only its total. Identify large individual files only inside promising subtrees, using metadata rather than reading file contents.
- Explicitly report permission-denied, missing, timed-out, excluded, or changing paths. Partial measurements are lower bounds, never zero usage. Keep raw output in a unique temporary location if it is large.
- No cleanup, service starts, cloud downloads, package installation, or settings changes. Stop a stalled scan and report its boundary rather than repeatedly retrying the same broad traversal.

Poll long commands without blocking user updates. If delegation itself is unavailable, disclose that constraint and perform bounded work locally. If only Luna is unavailable, use the inexpensive high-effort fallback above rather than abandoning delegation.

## Keep scans efficient

Use [scripts/scan_roots.py](scripts/scan_roots.py) for sequential bounded filesystem scans instead of rebuilding a timeout wrapper. Pass disjoint, prefiltered roots and a new per-worker evidence directory:

```sh
python3 scripts/scan_roots.py --output /absolute/new-evidence-dir --depth 2 --timeout 60 /absolute/root-a /absolute/root-b
```

The helper records metadata directly for loose files, skips symlink roots, saves raw output and a JSON ledger, and uses `subprocess.run(timeout=...)` without fixed sleeps. The helper rejects an evidence directory inside a scanned root, preventing it from counting its own changing output. Place evidence outside that worker’s roots, or partition the broad root into children while excluding the evidence subtree. The coordinator must still exclude cloud scopes and mounted/firmlink aliases before passing roots; the helper does not discover those boundaries. Treat rows from a partial root conservatively unless their own subtree was separately verified. Do not add one-second polling loops per path: many directory scans finish in milliseconds.

Create one unique temporary run evidence directory and give each worker its own subdirectory. Track its size separately so audit-created output is not mistaken for pre-existing usage; retain compact evidence and report its location and size. Keep a small machine-readable ledger of root, command, start/end timestamps, elapsed seconds, exit status, timeout, total KiB or null, and stdout/stderr paths. Return only top rows and coverage summaries to the main agent, not full directory listings or manifests. Use numeric IDs for evidence filenames so punctuation in source paths cannot collide.

Enumerate immediate children with `os.scandir` (including hidden entries, without following symlinks). For root-level regular files, collect `lstat().st_blocks * 512` instead of launching one `du` process per file; keep logical bytes separate and deduplicate hard-link identities within the partition. Scan independent directories with a bounded subprocess, typically 60 seconds per root. On timeout, terminate/reap that process, retain partial output, and continue other roots. Never treat a missing parent-total row as a complete total.

For broad category roots where two levels will explain ownership, capture `du -k -x -d 2` once and reuse its saved rows for ranking and drill-down. Depth 1 traverses the same tree, so repeatedly increasing depth wastes I/O. Choose a shallower output for very wide trees. Re-scan only a leading subtree needing deeper explanation, a changed path, or a representative verification target. Share initial leaders only as provisional progress while slower work continues. Final rankings require every assigned root to be complete or explicitly marked incomplete; a missing total cannot be ranked as smaller than completed roots.

If a normally substantial category returns tiny totals with pervasive access errors, perform at most one permitted read-only retry outside the sandbox. Replace the first measurement with the retry result; do not add them. Remaining denials are explicit coverage gaps, not evidence of small usage. Do not retry TCC-protected paths indefinitely.

For a later run, prior ledgers can prioritize scan order and identify slow/blocked roots, but old sizes are not current measurements. If a previous permitted retry already established unchanged privacy restrictions in the current session, keep one fresh bounded measurement and report the gap; do not repeat the same escalation for every denied root. Retry only if access conditions or evidence change. Do not skip a subtree merely because its top-directory mtime is unchanged. Re-measure before reporting present usage.

When evaluating efficiency, record first-pass wall time, subprocess count, traversal depth, roots covered, incomplete roots, and time spent on deeper attribution separately. Compare equivalent scopes; label warm filesystem-cache effects and changed coverage as confounders. Do not claim a speedup from fewer commands alone or compare an entire detailed run against an earlier shallow pass.

## Reconcile and investigate

Rank numeric allocated sizes, converting KiB to GiB consistently. Drill into the largest unexplained consumers until the result identifies meaningful apps, datasets, build artifacts, backups, media, or model files rather than stopping at `Library` or `Application Support`.

Check representative leading paths in the main agent, and reconcile child totals with their parents. Prefer an independent metadata check for a large file or identity rather than rerunning an entire tree solely for reassurance. Never add a parent and its children into the same total. Independently scanned hard-linked files may be counted more than once; APFS clones, compression, sparse files, snapshots, purgeable space, and shared container capacity mean a `du` total is not unique physical usage or guaranteed deletion savings. Label logical file sizes separately if used. Do not force filesystem totals to equal `df` by assigning the difference to an invented category.

Always check local image storage for Apple's `container` runtime and Docker if present. This is inventory only; Apple's runtime remains the preferred runtime for local container work. Discover installed commands, app bundles, standard data directories, and Docker-compatible local stores (such as Colima or OrbStack) when evidence indicates they exist. A broken `/usr/local/bin/docker` symlink is not an installed Docker runtime. Missing CLI does not prove its old disk images are absent.

For Apple container, consult installed `container image --help` and read-only list/inspect or disk-usage commands. Inventory all image references, not just running containers. Compare the image-list count with the installed runtime’s disk-usage count. If they differ, inspect local runtime state and image manifests for internal runtime/builder images or unreferenced artifacts; a tagged-image list alone may omit them. Name internal images in the report where metadata permits. Keep current image snapshots, content blobs, and unreferenced artifacts distinct and avoid adding overlapping store totals. Report image/content blobs, unpacked snapshots, writable container disks, volumes, and build cache separately where available. If runtime queries fail, do not start the service: inspect local OCI index/manifest metadata and file allocation instead, reporting inventory gaps. Distinguish allocated size from sparse VM logical capacity.

For Docker, check the selected context before connecting: query only a local daemon, never remote infrastructure for a Mac disk audit. If available locally, use `docker image ls -a --no-trunc` and `docker system df -v` to inventory images, shared/unique layers, containers, volumes, and build cache. If stopped/unavailable, measure existing Docker VM disks and report that per-image attribution is unavailable. Do not start Docker or change contexts. Never sum per-image logical sizes as unique disk usage; shared layers, unpacked snapshots, and sparse backing disks overlap. Save the full image inventory in evidence and show the largest items in the report. Do not prune images or caches.

Use existing tools; no package installs are needed for a normal audit.

Protected macOS paths may require Full Disk Access. Record the unreadable scope; elevated shell access does not necessarily overcome TCC. Avoid repeated denied traversals. Cloud-managed directories can stall and logical sizes may describe nonresident data: bound or skip stalled subtrees, report the gap, and do not read contents to force downloads.

## Attribute large directories to useful names

Expand leading categories until the reader can identify what occupies the space. For project folders, distinguish build runs, build caches, toolchains, source checkouts, dependency stores, datasets, and model files according to observed paths; do not assume a folder named `build` is wholly disposable.

For simulator devices, measure individual directories under the discovered CoreSimulator `Devices` root and read their `device.plist` metadata using `plistlib`. Join size to device name, runtime identifier/version, and UDID. No simulator needs to boot and no service needs to start. Include a short UDID suffix when multiple devices share a name; retain the full path and identifier in the detailed artifact. If metadata is missing, use the directory identifier and mark the name unknown. Do not interpret stored device state as confirmed live runtime state.

Keep simulator devices, DeviceSupport versions, DerivedData, runtime backing images, and system simulator caches as distinct branches at their actual locations. Map runtime image paths to platform/version through available asset metadata or mounted-image information. For other large opaque stores, read only the minimal descriptive manifest/plist needed to name the object; do not inspect personal documents, credentials, or file contents merely to measure usage.

## Deliver a responsive HTML report

Produce a **standalone `report.html` as the primary deliverable**, not a Markdown report. Use [scripts/render_report.py](scripts/render_report.py) with the JSON schema in [references/report-input.md](references/report-input.md):

```sh
python3 scripts/render_report.py --input /absolute/audit.json --output /absolute/report.html
```

Keep the JSON and HTML in run evidence outside this skill and outside any public checkout. Reports can contain private file names and paths; generating a report never authorizes publishing or uploading it. Public examples must be fictional. Do not copy a real audit into repository fixtures, screenshots, commit messages, or documentation.

The report must work offline without external scripts, fonts, analytics, or network requests. It must follow the system's light/dark preference with `prefers-color-scheme` and `color-scheme`, adapt to narrow mobile screens, wrap long paths without page overflow, and support keyboard navigation. Use expandable tree branches with visible sizes, names, and coverage status. Treat paths, labels, image references, and notes as untrusted text and HTML-escape them. Never inject raw filesystem strings into HTML or script contexts.

Sort sibling items by allocated size and expand leading categories by 2–4 meaningful levels. Show individually named simulator devices and runtime versions, the largest build runs/caches/toolchains, and named image/container storage. Preserve the full measured tree and all simulator/image inventories in the artifact; the chat response should link the HTML and summarize the main findings rather than repeat a huge table.

Build hierarchy from actual parent paths, not substring matches or labels. Do not invent an additive parent for unrelated locations. Children are already included in parents. Include all measured disjoint roots in the accounting input, not only the largest displayed categories. Mark partial measurements as lower bounds and absent totals as unknown, never zero. Calculate an `other measured items` remainder only from compatible, complete accounting; never hide denied paths or negative residuals inside it. Explain separately scanned hard links, clones, and live changes when child totals do not reconcile.

**Always display unreconciled space prominently**, even when zero or unavailable. For the same filesystem/volume scope and measurement window, report:

- Volume-used bytes from filesystem/APFS metadata.
- Measured bytes from disjoint root totals, excluding nested rows and alias mounts.
- Signed difference: volume-used bytes minus measured bytes, shown as unreconciled space.
- Coverage gaps and plausible accounting limitations, without assigning the difference to an invented category or promising it can be freed.

Do not subtract a Data-only inventory from whole-container usage. Keep shared APFS capacity/free-space context separate and explain its scope. If comparable volume usage is unavailable or root overlap remains unresolved, report the unreconciled value as **unknown** with the missing check. A negative result is an accounting mismatch to investigate, not negative free space; do not clamp it to zero. Partial measurements make the comparison incomplete. Unreconciled space is not a cleanup estimate.

Show CLI image sizes separately from physical tree allocations because layers may be shared. Include a concise coverage section for unreadable, skipped, timed-out, cloud-managed, or changing roots. If useful, identify specific cleanup candidates with retention/re-download implications, but size alone is not evidence of safe deletion. Cleanup requires authorization covering the targets.

Before delivery, generate a report with representative synthetic data and verify tree hierarchy, escaped text, arithmetic, light/dark styling, keyboard expansion, and narrow-screen layout. Keep real audit results local. Link the HTML artifact and state material unknowns in the final answer.
