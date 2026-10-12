#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pagination-integrity-check — reconcile collected pagination responses.

Input: a JSON array or JSONL stream of page records.

Offset mode (records with "page" + "ids"):
  page-gap        (error)   page numbers skip (1,2,4)
  duplicate-page  (error)   same page number appears twice
  negative-page   (error)   page number < 0
  id-overlap      (error)   the same id appears on two pages
  malformed-record(error)   record missing required keys / wrong types
  empty-page      (warning) a non-final page returned zero ids
  has-more-true   (warning) the final page still claims has_more=true

Cursor mode (records with "cursor" + "next_cursor"):
  chain-break     (error)   page[i].cursor != page[i-1].next_cursor
  cursor-cycle    (error)   a next_cursor value is revisited
  id-overlap      (error)   same id on two pages
  malformed-record(error)   record missing required keys
  empty-page      (warning) a non-final page returned zero ids
  dangling-next   (warning) final page's next_cursor is non-null

Report includes a reconciliation summary: total ids, unique ids, and the
list of missing page numbers. Exit: 0 clean-or-warnings, 1 errors, 2 I/O.
Pure stdlib. Python 3.8+.
"""
import argparse
import json
import sys

__version__ = "0.1.1"


def load_records(text):
    """Parse JSON array or JSONL; return (records, parse_errors)."""
    text = text.strip()
    if not text:
        return [], []
    if text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data, []
            return [], [{"line": 1, "message": "top-level JSON is not an array"}]
        except ValueError as e:
            return [], [{"line": 1, "message": "invalid JSON: %s" % e}]
    if text.startswith("{"):
        # single JSON value: only an array is a valid page collection;
        # multi-line JSONL (loads fails with "Extra data") falls through
        try:
            json.loads(text)
            return [], [{"line": 1, "message":
                         "top-level JSON is a single object, not an array"}]
        except ValueError:
            pass  # likely JSONL; handled below
    records, errs = [], []
    for ln, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError as e:
            errs.append({"line": ln, "message": "invalid JSONL: %s" % e})
    return records, errs


def _detect_mode(records):
    if not records:
        return "offset"
    has_page = sum(1 for r in records
                   if isinstance(r, dict) and "page" in r)
    has_cursor = sum(1 for r in records
                     if isinstance(r, dict) and "cursor" in r)
    if has_cursor > 0 and has_cursor >= has_page:
        return "cursor"
    return "offset"


def check_offset(records):
    findings = []

    def add(rule, severity, idx, msg):
        findings.append({"rule": rule, "severity": severity,
                         "record": idx, "message": msg})

    seen_pages = {}
    seen_ids = {}
    missing = []
    total, unique = 0, 0
    last = None
    for i, rec in enumerate(records):
        if not isinstance(rec, dict) or "page" not in rec or "ids" not in rec:
            add("malformed-record", "error", i,
                "record needs 'page' and 'ids' keys")
            continue
        page, ids = rec["page"], rec["ids"]
        if not isinstance(page, int) or isinstance(page, bool):
            add("malformed-record", "error", i, "'page' must be an integer")
            continue
        if not isinstance(ids, list):
            add("malformed-record", "error", i, "'ids' must be a list")
            continue
        if page < 0:
            add("negative-page", "error", i, "page number %d is negative" % page)
        if page in seen_pages:
            add("duplicate-page", "error", i,
                "page %d already collected at record %d" % (page, seen_pages[page]))
        else:
            seen_pages[page] = i
        for rid in ids:
            total += 1
            try:
                hash(rid)
                key = rid
            except TypeError:
                key = json.dumps(rid, sort_keys=True, ensure_ascii=False,
                                 default=repr)
            if key in seen_ids:
                if seen_ids[key] != page:
                    add("id-overlap", "error", i,
                        "id %r on page %d already seen on page %d"
                        % (rid, page, seen_ids[key]))
            else:
                seen_ids[key] = page
                unique += 1
        last = (i, page, ids, rec.get("has_more"))
    pages = sorted(p for p in seen_pages if p >= 0)
    if pages:
        for expected in range(min(pages), max(pages) + 1):
            if expected not in seen_pages:
                missing.append(expected)
                add("page-gap", "error", -1,
                    "missing page %d between %d and %d"
                    % (expected, min(pages), max(pages)))
        for i, rec in enumerate(records):
            if isinstance(rec, dict) and rec.get("ids") == [] \
                    and i != len(records) - 1:
                add("empty-page", "warning", i,
                    "page %d returned zero ids but is not final" % rec.get("page"))
        if last is not None and last[3] is True:
            add("has-more-true", "warning", last[0],
                "final page still claims has_more=true")
    return {"mode": "offset", "records": len(records),
            "total_ids": total, "unique_ids": unique,
            "missing_pages": missing, "findings": findings}


def check_cursor(records):
    findings = []

    def add(rule, severity, idx, msg):
        findings.append({"rule": rule, "severity": severity,
                         "record": idx, "message": msg})

    seen_ids = {}
    visited_cursors = set()
    seen_next = {}
    total, unique = 0, 0
    prev_next = None
    last = None
    for i, rec in enumerate(records):
        if not isinstance(rec, dict) or "cursor" not in rec \
                or "next_cursor" not in rec:
            add("malformed-record", "error", i,
                "record needs 'cursor' and 'next_cursor' keys")
            continue
        cur, nxt = rec["cursor"], rec["next_cursor"]
        ids = rec.get("ids", [])
        if not isinstance(ids, list):
            add("malformed-record", "error", i, "'ids' must be a list")
            continue
        if prev_next is not None and cur != prev_next:
            add("chain-break", "error", i,
                "cursor %r does not match previous next_cursor %r"
                % (cur, prev_next))
        if cur in visited_cursors:
            add("cursor-cycle", "error", i,
                "cursor %r revisits record %d" % (cur, seen_next[cur]))
        visited_cursors.add(cur)
        seen_next[cur] = i
        for rid in ids:
            total += 1
            try:
                hash(rid)
                key = rid
            except TypeError:
                key = json.dumps(rid, sort_keys=True, ensure_ascii=False,
                                 default=repr)
            if key in seen_ids:
                if seen_ids[key] != i:
                    add("id-overlap", "error", i,
                        "id %r already seen on record %d" % (rid, seen_ids[key]))
            else:
                seen_ids[key] = i
                unique += 1
        if ids == [] and "ids" in rec and i != len(records) - 1:
            add("empty-page", "warning", i, "non-final page returned zero ids")
        prev_next = nxt
        last = (i, nxt)
    if last is not None and last[1] is not None:
        add("dangling-next", "warning", last[0],
            "final next_cursor %r is non-null" % last[1])
    return {"mode": "cursor", "records": len(records),
            "total_ids": total, "unique_ids": unique,
            "missing_pages": [], "findings": findings}


def check_records(records, mode="auto"):
    parse_mode = mode
    if parse_mode == "auto":
        parse_mode = _detect_mode(records)
    if parse_mode == "cursor":
        result = check_cursor(records)
    else:
        result = check_offset(records)
    result["findings"].sort(key=lambda f: (f["record"], f["rule"]))
    return result


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="pagination-integrity-check",
        description="Reconcile collected pagination responses: missing pages, "
                    "overlapping ids, cursor chain breaks.")
    p.add_argument("file", help="JSON array or JSONL file ('-' for stdin)")
    p.add_argument("--mode", choices=("auto", "offset", "cursor"),
                   default="auto")
    p.add_argument("--json", action="store_true")
    p.add_argument("--version", action="version",
                   version="%(prog)s " + __version__)
    args = p.parse_args(argv)
    try:
        if args.file == "-":
            text = sys.stdin.read()
        else:
            with open(args.file, "r", encoding="utf-8-sig") as f:
                text = f.read()
    except OSError as e:
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print("error: cannot read %s: %s" % (args.file, e), file=sys.stderr)
        return 2
    records, parse_errors = load_records(text)
    result = check_records(records, mode=args.mode)
    result["parse_errors"] = parse_errors
    for pe in parse_errors:
        result["findings"].append({"rule": "parse-error", "severity": "error",
                                   "record": pe["line"], "message": pe["message"]})
    errors = [f for f in result["findings"] if f["severity"] == "error"]
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for f in result["findings"]:
            print("%-16s %-7s record %s: %s"
                  % (f["rule"], f["severity"], f["record"], f["message"]))
        extra = ("missing pages: %s" % result["missing_pages"]) \
            if result["missing_pages"] else ""
        print("mode=%s records=%d total_ids=%d unique_ids=%d "
              "%d error(s), %d warning(s) %s"
              % (result["mode"], result["records"], result["total_ids"],
                 result["unique_ids"], len(errors),
                 len(result["findings"]) - len(errors), extra))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
