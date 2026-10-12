# -*- coding: utf-8 -*-
"""self_test for pagination-integrity-check — v2 template, four defenses:
1) SystemExit/Exception capture  2) Unicode-safe matching
3) fixtures written with newline=""  4) last line: SUMMARY: PASS n/n
"""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pagination_check as mod  # noqa: E402

main = mod.main


def run_cli(argv):
    buf_out, buf_err = io.StringIO(), io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            code = main(argv) or 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception as e:  # noqa: BLE001
        code = 1
        buf_err.write(repr(e))
    return code, buf_out.getvalue(), buf_err.getvalue()


FIX = tempfile.mkdtemp(prefix="pic_selftest_")


def wfile(name, content):
    path = os.path.join(FIX, name)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return path


def jrecs(*recs):
    return json.dumps(list(recs))


def rules(records, mode="auto"):
    return [f["rule"] for f in mod.check_records(records, mode)["findings"]]


def opage(n, ids, has_more=None):
    r = {"page": n, "ids": ids}
    if has_more is not None:
        r["has_more"] = has_more
    return r


def cpage(cur, nxt, ids=None):
    return {"cursor": cur, "next_cursor": nxt, "ids": ids or []}


CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


# ---------- [A] functional offset ----------
@case("clean offset pages pass")
def t01():
    r = mod.check_records([opage(0, ["a", "b"]), opage(1, ["c"])])
    assert r["findings"] == [] and r["mode"] == "offset", r


@case("page-gap fires")
def t02():
    assert "page-gap" in rules([opage(0, ["a"]), opage(2, ["b"])])


@case("missing_pages lists the gap")
def t03():
    r = mod.check_records([opage(0, []), opage(2, [])])
    assert r["missing_pages"] == [1], r


@case("duplicate-page fires")
def t04():
    assert "duplicate-page" in rules([opage(1, ["a"]), opage(1, ["b"])])


@case("negative-page fires")
def t05():
    assert "negative-page" in rules([opage(-1, ["a"]), opage(0, ["b"])])


@case("id-overlap fires across pages")
def t06():
    assert "id-overlap" in rules([opage(0, ["a"]), opage(1, ["a"])])


@case("id-overlap inside one page not double-counted error")
def t07():
    r = mod.check_records([opage(0, ["a", "a"]), opage(1, ["b"])])
    assert "id-overlap" not in [f["rule"] for f in r["findings"]], r


@case("empty-page warning on non-final empty page")
def t08():
    r = mod.check_records([opage(0, ["a"]), opage(1, []), opage(2, ["b"])])
    assert "empty-page" in rules([opage(0, ["a"]), opage(1, []), opage(2, ["b"])])


@case("final empty page is not a warning")
def t09():
    r = mod.check_records([opage(0, ["a"]), opage(1, [])])
    assert "empty-page" not in [f["rule"] for f in r["findings"]], r


@case("has-more-true warning on final page")
def t10():
    r = mod.check_records([opage(0, ["a"], has_more=True)])
    assert "has-more-true" in [f["rule"] for f in r["findings"]]


@case("has_more false on final page is clean")
def t11():
    assert mod.check_records([opage(0, ["a"], has_more=False)])["findings"] == []


@case("malformed-record missing ids")
def t12():
    assert "malformed-record" in rules([{"page": 0}])


@case("malformed-record non-int page")
def t13():
    assert "malformed-record" in rules([opage("1", ["a"])])


@case("non-dict record is malformed")
def t14():
    assert "malformed-record" in rules(["nope"])


@case("reconciliation totals correct")
def t15():
    r = mod.check_records([opage(0, ["a", "b"]), opage(1, ["c", "a"])])
    assert r["total_ids"] == 4 and r["unique_ids"] == 3, r


# ---------- [A] functional cursor ----------
@case("clean cursor chain passes")
def t16():
    r = mod.check_records([cpage(None, "c1", ["a"]), cpage("c1", None, ["b"])])
    assert r["findings"] == [] and r["mode"] == "cursor", r


@case("chain-break fires")
def t17():
    r = rules([cpage(None, "c1", ["a"]), cpage("WRONG", None, ["b"])])
    assert "chain-break" in r, r


@case("cursor-cycle fires")
def t18():
    r = rules([cpage(None, "c1"), cpage("c1", "c0"), cpage("c0", "c1"),
               cpage("c1", None)])
    assert "cursor-cycle" in r, r


@case("id-overlap fires in cursor mode")
def t19():
    assert "id-overlap" in rules([cpage(None, "c1", ["a"]),
                                  cpage("c1", None, ["a"])])


@case("dangling-next warning")
def t20():
    r = rules([cpage(None, "c1", ["a"]), cpage("c1", "c2", ["b"])])
    assert "dangling-next" in r and "cursor-cycle" not in r, r


@case("cursor empty-page warning")
def t21():
    r = rules([cpage(None, "c1", ["a"]), cpage("c1", "c2", []),
               cpage("c2", None, ["b"])])
    assert "empty-page" in r, r


@case("cursor malformed record")
def t22():
    assert "malformed-record" in rules([{"cursor": None}])


@case("auto mode detects cursor input")
def t23():
    r = mod.check_records([cpage(None, "c1", ["a"])])
    assert r["mode"] == "cursor"


@case("auto mode detects offset input")
def t24():
    r = mod.check_records([opage(0, ["a"])])
    assert r["mode"] == "offset"


@case("forced mode override works")
def t25():
    r = mod.check_records([cpage(None, "c1")], mode="offset")
    assert r["mode"] == "offset" and any(
        f["rule"] == "malformed-record" for f in r["findings"])


# ---------- [A] CLI ----------
@case("json output shape and exit 1 on error")
def t26():
    path = wfile("bad.json", jrecs(opage(0, ["a"]), opage(2, ["b"])))
    code, out, _ = run_cli([path, "--json"])
    data = json.loads(out)
    assert code == 1 and data["missing_pages"] == [1]
    assert data["findings"][0]["rule"] == "page-gap"


@case("clean file exits 0")
def t27():
    path = wfile("ok.json", jrecs(opage(0, ["a"]), opage(1, ["b"])))
    code, out, _ = run_cli([path])
    assert code == 0 and "0 error(s)" in out, out


@case("warning-only exits 0")
def t28():
    path = wfile("warn.json", jrecs(opage(0, ["a"]), opage(1, [])))
    code, _, _ = run_cli([path])
    assert code == 0


@case("JSONL input accepted")
def t29():
    lines = "\n".join(json.dumps(r) for r in
                      (opage(0, ["a"]), opage(1, ["b"])))
    path = wfile("s.jsonl", lines)
    code, out, _ = run_cli([path])
    assert code == 0 and "unique_ids=2" in out, out


@case("invalid JSONL line reported as parse-error")
def t30():
    path = wfile("broken.jsonl", '{"page":0,"ids":["a"]}\nNOT JSON\n')
    code, out, _ = run_cli([path, "--json"])
    data = json.loads(out)
    assert code == 1 and any(f["rule"] == "parse-error" for f in data["findings"])


@case("invalid top-level JSON reported")
def t31():
    path = wfile("broken.json", "{oops")
    code, out, _ = run_cli([path, "--json"])
    data = json.loads(out)
    assert code == 1 and any(f["rule"] == "parse-error" for f in data["findings"])


@case("top-level non-array JSON reported")
def t32():
    path = wfile("obj.json", '{"page": 0}')
    code, out, _ = run_cli([path, "--json"])
    data = json.loads(out)
    assert code == 1 and any(f["rule"] == "parse-error" for f in data["findings"])


@case("stdin mode works")
def t33():
    buf = io.StringIO(jrecs(opage(0, ["a"]), opage(1, ["b"])))
    old = sys.stdin
    sys.stdin = buf
    try:
        code, out, _ = run_cli(["-"])
    finally:
        sys.stdin = old
    assert code == 0 and "records=2" in out, out


@case("--mode cursor forced via CLI")
def t34():
    path = wfile("m.json", jrecs(opage(0, ["a"])))
    code, out, _ = run_cli([path, "--mode", "cursor"])
    assert code == 1 and "malformed-record" in out, out


@case("findings always have four keys")
def t35():
    for f in mod.check_records([opage(0, ["a"]), opage(2, ["a"])])["findings"]:
        assert set(f) == {"rule", "severity", "line", "message"} | {"record"} \
            or set(f) == {"rule", "severity", "record", "message"}


# ---------- [B] error paths ----------
@case("missing file exits 2")
def t36():
    code, _, err = run_cli([os.path.join(FIX, "nope.json")])
    assert code == 2 and "cannot read" in err, err


@case("missing file --json prints json error")
def t37():
    code, out, _ = run_cli([os.path.join(FIX, "nope.json"), "--json"])
    assert code == 2 and "error" in json.loads(out)


@case("directory as input exits 2")
def t38():
    assert run_cli([FIX])[0] == 2


@case("no arguments raises SystemExit 2")
def t39():
    try:
        main([])
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert e.code == 2


@case("--help exits 0")
def t40():
    code, out, _ = run_cli(["--help"])
    assert code == 0 and "usage" in out.lower()


@case("--version exits 0")
def t41():
    code, out, _ = run_cli(["--version"])
    assert code == 0 and "0.1.1" in out


@case("unknown flag exits 2")
def t42():
    assert run_cli(["--bogus"])[0] == 2


@case("invalid --mode value exits 2")
def t43():
    assert run_cli(["x.json", "--mode", "bogus"])[0] == 2


@case("empty input yields zero records, no crash")
def t44():
    r = mod.check_records([])
    assert r["records"] == 0 and r["findings"] == []


@case("repeated runs deterministic")
def t45():
    recs = [opage(0, ["a"]), opage(2, ["b"])]
    assert mod.check_records(recs) == mod.check_records(recs)


# ---------- [C] extreme edge ----------
@case("empty JSON array")
def t46():
    r = mod.check_records([])
    assert r["total_ids"] == 0 and r["missing_pages"] == []


@case("unicode ids")
def t47():
    r = mod.check_records([opage(0, ["订单-1"]), opage(1, ["订单-2"])])
    assert r["findings"] == [] and r["unique_ids"] == 2, r


@case("unicode id overlap detected")
def t48():
    r = mod.check_records([opage(0, ["订单-1"]), opage(1, ["订单-1"])])
    assert "id-overlap" in [f["rule"] for f in r["findings"]]


@case("huge page numbers sparse gap")
def t49():
    r = mod.check_records([opage(0, ["a"]), opage(100000, ["b"])])
    assert len(r["missing_pages"]) == 99999, len(r["missing_pages"])


@case("10000 pages clean pass performance path")
def t50():
    recs = [opage(i, ["id-%d" % i]) for i in range(10000)]
    r = mod.check_records(recs)
    assert r["unique_ids"] == 10000 and r["findings"] == []


@case("bool page number is malformed not int")
def t51():
    assert "malformed-record" in rules([opage(True, ["a"])])


@case("null ids is malformed")
def t52():
    assert "malformed-record" in rules([{"page": 0, "ids": None}])


@case("extra keys tolerated")
def t53():
    r = mod.check_records([dict(opage(0, ["a"]), fetched_at="2026-01-01")])
    assert r["findings"] == []


@case("cursor null start and end chain")
def t54():
    r = mod.check_records([cpage(None, None, ["a"])])
    assert r["findings"] == [], r


@case("single page single id")
def t55():
    r = mod.check_records([opage(0, ["only"])])
    assert r["unique_ids"] == 1 and r["findings"] == []


@case("page ids with mixed types")
def t56():
    r = mod.check_records([opage(0, [1, "a", None, {"x": 1}]), opage(1, [2])])
    assert r["unique_ids"] == 5 and r["findings"] == [], r


@case("duplicate detection is value-based (1 vs '1' differ)")
def t57():
    r = mod.check_records([opage(0, [1]), opage(1, ["1"])])
    assert r["unique_ids"] == 2 and r["findings"] == [], r


@case("cursor cycle with reused null")
def t58():
    r = rules([cpage(None, "a"), cpage("a", None)])
    assert "cursor-cycle" not in r, r


@case("BOM prefix tolerated")
def t59():
    path = os.path.join(FIX, "bom.json")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(jrecs(opage(0, ["a"]), opage(1, ["b"])))
    code, out, _ = run_cli([path])
    assert code == 0, out


@case("CRLF JSONL tolerated")
def t60():
    lines = "\r\n".join(json.dumps(r) for r in (opage(0, ["a"]), opage(1, ["b"])))
    path = wfile("crlf.jsonl", lines)
    code, _, _ = run_cli([path])
    assert code == 0


@case("empty-page rule uses record index not page number")
def t61():
    r = mod.check_records([opage(5, ["a"]), opage(6, []), opage(7, ["b"])])
    f = [x for x in r["findings"] if x["rule"] == "empty-page"][0]
    assert f["record"] == 1, r


@case("full pipeline contract via CLI")
def t62():
    path = wfile("c62.json", jrecs(opage(0, ["a"]), opage(1, ["a"]),
                                   opage(3, ["b"])))
    code, out, _ = run_cli([path])
    assert code == 1 and "id-overlap" in out and "page-gap" in out \
        and "missing pages: [2]" in out, out


@case("summary line format stable")
def t63():
    path = wfile("c63.json", jrecs(opage(0, ["a"]), opage(1, ["b"])))
    code, out, _ = run_cli([path])
    assert "mode=offset records=2 total_ids=2 unique_ids=2 0 error(s), 0 warning(s)" in out, out


@case("cursor mode records without ids key tolerated")
def t64():
    r = mod.check_records([{"cursor": None, "next_cursor": "a"},
                           {"cursor": "a", "next_cursor": None}])
    assert r["findings"] == [] and r["total_ids"] == 0, r


@case("mixed offset and cursor fields prefers cursor")
def t65():
    recs = [dict(cpage(None, "c1", ["a"]), page=0),
            dict(cpage("c1", None, ["b"]), page=1)]
    r = mod.check_records(recs)
    assert r["mode"] == "cursor" and r["findings"] == [], r


class ToolTests(unittest.TestCase):
    pass


def _name(i, n):
    return "test_%03d_%s" % (i, re.sub(r"\W+", "_", n))


for _i, (_n, _fn) in enumerate(CASES):
    setattr(ToolTests, _name(_i, _n), lambda self, _f=_fn: _f())


if __name__ == "__main__":
    r = unittest.TextTestRunner(verbosity=0).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules["__main__"]))
    total, fails = r.testsRun, len(r.failures) + len(r.errors)
    for t, _ in r.failures + r.errors:
        print("FAIL:", t.id().split(".")[-1])
    print("SUMMARY: PASS %d/%d" % (total - fails, total))
    sys.exit(0 if fails == 0 else 1)
