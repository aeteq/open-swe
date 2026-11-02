# Constrain the SDK's transitive dependencies to their fixed releases

**Verdict: upstream as-is.** A security fix any project that installs `managed-deepagents` needs; upstream's own manifest should carry it too.

**Changed:** `packages/pypi/pyproject.toml` (new `[tool.uv] constraint-dependencies`) and the `packages/pypi/uv.lock` it regenerates.

## What

A `[tool.uv] constraint-dependencies` floor pins three transitive dependencies of the SDK's own `uv.lock` to the releases that clear their advisories:

- `authlib==1.9.1` (from `mcp`/`fastmcp`, critical)
- `certifi==2026.10.18` (from `httpx`, critical)
- `dnspython==2.9.0` (from `email-validator`, high)

## Why

Trivy flagged the SDK's `uv.lock` on `aeteq/open-swe`'s default branch. `scripts/vendor.py` copies upstream's `uv.lock` verbatim, so a bare lockfile edit is fragile: the next vendoring would three-way merge or overwrite it. A constraint in the manifest keeps the fixed releases through any later `uv lock`, so the lockfile never re-resolves below them.

## Upstream

The constraint block and the regenerated lockfile, exactly as they stand here. Drop a floor once upstream's own manifest requires the fixed release.
