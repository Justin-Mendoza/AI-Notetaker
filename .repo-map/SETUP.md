# Incremental repository maps

JSON summaries are stored on a dedicated `repo-map` branch. Each subsystem has its own GitHub-readable Mermaid page, PNG diagrams and PDF. Default-branch merges update the affected subsystems; generated output does not go onto the application branch.

## Activate

1. Under **Settings → Secrets and variables → Actions → New repository secret**, add `KYMA_API_KEY` with your Kyma key. Do not put the key in source code.
2. Defaults: API base `https://api.kymaapi.com/v1`, model `deepseek-v4.1-flash`. Optional Actions **Variables** `LLM_BASE_URL` and `LLM_MODEL` override these. The endpoint must support Chat Completions with JSON-object responses. Public Kyma docs also list `https://kymaapi.com/v1`; if the configured host redirects, use the canonical base URL explicitly. This client does not follow authenticated redirects.
3. Review source scopes and subsystem definitions in `config.json` before sending private source to the provider. Exclude confidential data explicitly. Secret-file exclusions and credential-line redaction are heuristics, not complete protection for arbitrary private records.
4. Commit/push setup to the default branch and enable Actions. The workflow needs `contents: write` to create/update **only `repo-map`** using GitHub's built-in token. Branch protection or organization policy can block that write; no personal access token is normally needed. Do not use `repo-map` as the application's default branch or for unrelated files.
5. Pushes/merges to the default branch run automatically; changes only to this guide are skipped. Feature-branch runs skip generation. You can also use **Actions → Update repository maps → Run workflow** on the default branch, with optional full refresh.

The first activated workflow run uses DeepSeek through Kyma to generate all initial subsystem maps and the overview automatically. No local seed is needed. Later runs compare with the last successful map revision and update affected maps. Each executed analysis uses Kyma credits. No schedules, untrusted PR execution, public website, or desktop popup is configured.

## Browse the results

Switch the GitHub branch selector to **repo-map**, open its README, and follow the subsystem links. Mermaid diagrams render directly in GitHub Markdown; PNG fallbacks and PDFs are available alongside them.

```text
repo-map branch
├── README.md                 overview and subsystem links
├── manifest.json             file hashes, map ownership, dependencies, revisions
├── update.json               last update scope, API calls and usage
├── overview/                 subsystem architecture views + PDF
└── maps/
    ├── api/                  example subsystem, chosen for your actual repo
    │   ├── map.json          summary, graph, evidence and metadata
    │   ├── README.md         readable Mermaid views and source links
    │   ├── diagram-01.mmd
    │   ├── diagram-01.png
    │   ├── repository-map.pdf
    │   └── coverage.json
    └── …
```

Successful runs also upload `repo-map-<run number>` under **Actions → completed run → Artifacts**, with a summary link. Download requires repository access and sign-in. Artifact retention is 30 days, subject to policy. The `repo-map` branch remains until deleted; normal Git version history applies, so artifacts do not expire its committed history.

## Define maps

`maps: {}` uses a deterministic directory grouping as a fallback. For better boundaries, configure actual subsystems:

```json
"maps": {
  "api": {"include": ["backend/*", "shared/contracts/*"], "depends_on": ["storage"]},
  "frontend": {"include": ["frontend/*", "shared/contracts/*"], "depends_on": ["api"]},
  "storage": {"include": ["database/*"], "depends_on": []}
}
```

Replace these examples with real paths. IDs are lowercase letters/digits/hyphens (start with a letter, at most 48 characters). Use at most 12 maps and ensure the total call budget can cover them. Shared files can belong to multiple maps. Relevant files not assigned to any explicit map are listed in `manifest.json`; resolve those omissions during setup.

`depends_on` means the map consumes another subsystem's interface or behavior. Resolvable relative JS imports and basic Python imports add dependency hints. Aliases, framework wiring, Go package paths, dynamic calls and cross-service contracts are not fully inferred; add dependencies explicitly. Globs use Python `fnmatch` against repo-relative paths (`*` also matches slashes). Global `include`/`exclude` apply before map scopes. Only tracked, eligible text is sent; `.gitignore` does not hide already tracked files.

## What updates

- File hashes detect changed, added, deleted and renamed eligible files against the last successful state.
- Changed maps and their transitive known dependents are rechecked conservatively, including removed dependency links. A body change can matter to a consumer even when the function signature stays the same.
- Only affected subsystem excerpts, changed-path context, and saved/neighbor summaries go to the API. This is not a diff-only prompt: current subsystem context is included to avoid stale relationships.
- Semantically unchanged presentation data reuses existing PNG/PDF bytes. Overview renders only when dependency topology changes. A styling-only change outside the source policy makes no model call.
- Removed maps are deleted from the saved state. The index shows each map's last analyzed revision, which can be older than the latest commit for unaffected maps.
- Config/model/renderer changes, divergent Git history, manual full refresh, and every 20 analysis updates refresh all maps. Full refresh still uses bounded excerpts, not every line.
- State is staged before replacing outputs. API/schema/layout failures publish nothing. Stale queued runs cannot regress a newer analyzed source revision. Publication is also skipped if the remote default branch has advanced while generation was running; a newer queued run catches up. Publication uses ordinary Git pushes, never force pushes.

The publisher writes only to `repo-map`; it does not update source branches, open PRs, or run application scripts. Branch filtering, a default-branch job guard and bot-token behavior prevent self-triggered map loops. Do not modify generated Mermaid/PNG/PDF files independently: JSON summaries/graphs are their source of truth.

## Readability and limits

Use focused top-down views: 2-6 nodes, at most 8 edges, short wrapped labels, and 1-2 sentence explanations (40 words maximum). Oversized model graphs are automatically split into small connected views after their source references are validated. Shared nodes repeat across views so no connection or evidence is discarded. The report records these splits; they need no extra API calls. The requested diagram count is a model target; splitting can create extra pages. Hard limits (64 raw nodes / 128 edges per graph and 64 views per map) still bound malformed or extreme output. Each PDF page shows one diagram. Rendering uses Graphviz at 144 dpi; Mermaid comes from the same graph. Node text is 22pt at layout time and must stay at least 12pt after fitting a PDF page; oversized layouts fail instead of silently shrinking. The fallback is not a general Mermaid ER/sequence renderer.

Default per-map analysis: 160 files, 18,000 source characters per file, 180,000 total source characters, 24,000-character batch target, 12 API calls (including synthesis), 6,000 output tokens per call, and six diagrams. A shared limit of 24 calls covers the entire update. Calls are allocated so remaining affected maps retain at least an analysis and synthesis call. Increase budgets deliberately or group scopes more broadly if needed. Runtime timeout is 60 minutes. Provider and Actions billing apply; request limits are not an exact dollar cap.

Coverage and source IDs prove that evidence locations were supplied, not that the model's interpretation is true. Excerpt truncation and call-budget omissions are recorded. Credential-like lines are redacted and common credential/build/dependency files excluded. Raw source snippets and raw model responses are not persisted as artifacts, but generated summaries can reveal architecture. Review who can read the repo and the chosen API provider's handling of submitted source.

No automatic API retry is made; a timed-out request can still incur a charge. HTTP/model/JSON/reference errors fail the run rather than publishing plausible partial output. Requested/reported models and any Kyma substitution are recorded. If a request fails, inspect the non-secret error and fix endpoint/model/access/configuration before rerunning.

## Local planning / optional seed

With committed source and an empty temporary directory, inspect ownership and invalidation without a key:

```sh
python3 .repo-map/incremental.py --repo . --state /tmp/my-repo-map-state --plan
```

No analysis or rendering is performed. The setup skill can author initial `maps/<id>/map.json` seeds locally and validate/render them with `--seed <seed-directory>`; this works only for empty state and needs no API key. Source paths/line ranges, findings and graph structure are checked. Publication of prepared seed state is a separate operation, not a consequence of planning.

For local full generation, use an existing Python 3.12+ environment with ReportLab and Graphviz `dot`. Keep state outside the source repo. The workflow installs its own tools, never application dependencies.

References: [Actions secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets), [workflow artifacts](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts), [Kyma Chat Completions](https://docs.kymaapi.com/api-reference/chat-completions).

### Architectural explanations

The overview PDF and Mermaid index bring together the first analyzed architecture view from each subsystem map. They show subsystem responsibilities and source-backed component relationships instead of generic import dependency sketches. Open each subsystem README for its finding citations. Generated maps emphasize component responsibilities, system boundaries, data ownership, and communication contracts. Each subsystem includes a concise architectural summary and short explanations beside its diagrams. Runtime flows illustrate the architecture where useful. Design rationale is included only when supported by inspected evidence. After updating the generator, the next run refreshes existing maps because generator changes invalidate the saved fingerprint.

### Diagnosing failures

The log names each subsystem before its analysis starts. Validation errors include the subsystem, stage, one-based diagram and node/edge positions, and the violated rule. For example: `subsystem retrieval: synthesis validation: diagrams[2]: node 4: duplicate node ID; first declared at node 1`. IDs may contain punctuation; each must be unique within its diagram. Length failures report actual and allowed sizes. Logs do not dump raw model responses or source excerpts. Saved state is published only after all affected maps succeed.

Long node and edge labels are shortened automatically for display. Their full wording remains in the generated README layout notes and map JSON; endpoints and evidence are unchanged. No extra model call is needed for this formatting step.

### Make maps understandable

The main view explains what a feature does, what starts it, and what it produces in familiar words. Internal class names and configuration details belong in source evidence or focused follow-up views. Each overview section includes a short explanation above its diagram. Dashed arrows identify connections that need confirmation; a reading key explains them once per diagram.

Descriptions longer than 40 words or 500 display characters are shortened automatically. Full explanations remain in layout notes. Titles and labels are also compacted for display. Structural errors, ambiguous duplicate IDs, missing evidence, and credential checks still stop publication with a specific diagnostic.

### Recover without restarting the entire analysis

`max_repair_calls` defaults to 1 (set it to 0 to disable). If synthesis produces a graph with missing evidence, duplicate IDs, or another validation error, one repair request receives the error and original findings. It must return a fully validated graph. Unsupported relationships are not published. The repair uses the existing subsystem and total call budgets; available repair capacity is reserved when the budget permits it. Transport failures and provider timeouts are not automatically retried.

The workflow uses a separate GitHub Actions cache for validated analysis batches and subsystem synthesis. It restores checkpoints before analysis and saves them even if a later subsystem or renderer fails. The next run reuses matching requests rather than paying to analyze the same excerpts again. Checkpoints contain normalized findings and map output, not API keys or raw source excerpts. Keys include exact request content, model/endpoint, output options, and generator version. A manual full refresh deliberately bypasses reuse. Cache eviction, outages, generator changes, or changed inputs can still require fresh calls.

For local CLI use, set `REPO_MAP_CHECKPOINTS` to a temporary directory outside the repository to enable checkpoints. Coverage and update JSON report `checkpoint_hits`; logs distinguish reused from freshly analyzed batches. The last successful published map is preserved if repair fails. Install the updated workflow as well as the updated scripts to retain checkpoints across GitHub runners.
