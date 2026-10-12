# Changelog

## v0.1.1 — 2026-10-13
- Round-2 fixes found by self-audit (6 failing cases → green):
  - single top-level JSON object `{...}` is now rejected as a parse error instead of being silently parsed as one JSONL record.
  - multi-line JSONL starting with `{` no longer misclassified after the above fix (fall-through restored).
  - auto-detection now prefers cursor mode on ties between page/cursor field counts (mixed records).
  - unhashable ids (dicts/lists) no longer crash the overlap scan; compared via canonical JSON.
  - intra-page duplicate ids no longer flagged as cross-page `id-overlap`; cursor records without an `ids` key no longer trigger `empty-page`.
- Self-test re-run: `python self_test.py` → `SUMMARY: PASS 65/65` (was 59/65 at first draft).

## v0.1.0 — 2026-10-13
- Initial implementation: JSON array / JSONL loader, offset mode (page-gap / duplicate-page / negative-page / id-overlap / malformed-record / empty-page / has-more-true), cursor mode (chain-break / cursor-cycle / id-overlap / malformed-record / empty-page / dangling-next), auto mode detection, reconciliation summary, CLI (file/stdin, `--mode`, `--json`, exit 0/1/2 contract).
- Self-test suite (functional / error / extreme-edge tiers), 65 cases at first draft.
