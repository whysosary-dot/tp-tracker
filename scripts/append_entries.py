#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tp-tracker 데이터 추가 스크립트 — Claude가 index.html을 직접 읽지 않고
새 엔트리 JSON만 전달하면 안전하게 append + updateLog 갱신 + JS 검증까지 수행한다.

사용법:
  python3 scripts/append_entries.py new_entries.json [--index path/to/index.html]

입력 JSON 형식:
{
  "date": "2026-07-02",                     // 오늘 날짜 (updateLog용)
  "add": {                                   // 종목별 신규 엔트리 (없으면 생략)
    "삼성전자": [
      { "date":"2026-07-01", "broker":"미래에셋증권", "tp":500000,
        "source":"https://...", "estYear":"2026E", "revenue":775.7, "op":438.0,
        "q2r":85.6, "q2op":66.5 }
    ]
  },
  "patch_last": {                            // 종목별: 가장 최근 항목에 없는 분기 필드만 보완 (없으면 생략)
    "SK하이닉스": { "q2r":25.1, "q2op":12.3, "q3r":26.0, "q3op":13.1 }
  }
}

동작:
- 중복(같은 date+broker+tp) 엔트리는 자동 skip
- patch_last는 이미 있는 필드는 건드리지 않음
- updateLog 맨 앞에 오늘 날짜 블록 추가(이미 있으면 items에 병합)
- 저장 전 JS 문법 검사(node) + 이중콤마 검사 — 실패 시 원본 유지 후 exit 1
출력: 변경 요약 (추가/보완/스킵 건수)
"""
import json, re, sys, subprocess, tempfile, os

FIELD_ORDER = ["date","broker","tp","source","estYear","revenue","op",
               "q1r","q1op","q2r","q2op","q3r","q3op","q4r","q4op","note"]

def js_val(v):
    if v is None: return "null"
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(int(v)) if float(v).is_integer() else str(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"

def serialize(e):
    parts = []
    for k in FIELD_ORDER:
        if k in e and e[k] is not None:
            parts.append(f"{k}:{js_val(e[k])}")
    for k in e:
        if k not in FIELD_ORDER and e[k] is not None:
            parts.append(f"{k}:{js_val(e[k])}")
    return "{ " + ", ".join(parts) + " }"

def find_array(content, stock):
    """종목명으로 해당 const 배열의 (시작, 닫는 `];` 위치)를 찾는다."""
    m = re.search(r"(\w+)\.forEach\(s => \{ entries\.push\(\{ id: Date\.now\(\) \+ Math\.random\(\), stock:'"
                  + re.escape(stock) + r"'", content)
    if not m:
        return None
    var = m.group(1)
    const_pos = content.rfind(f"const {var} = [", 0, m.start())
    if const_pos < 0:
        return None
    close_pos = content.rfind("];", const_pos, m.start())
    if close_pos < 0:
        return None
    return (const_pos, close_pos)

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    inp_path = sys.argv[1]
    idx_path = "index.html"
    if "--index" in sys.argv:
        idx_path = sys.argv[sys.argv.index("--index") + 1]
    with open(inp_path, encoding="utf-8") as f:
        job = json.load(f)
    with open(idx_path, encoding="utf-8") as f:
        content = f.read()

    today = job.get("date")
    added, patched, skipped, log_items = [], [], [], []

    # ── 1. 신규 엔트리 append ──
    for stock, ents in (job.get("add") or {}).items():
        for e in ents:
            loc = find_array(content, stock)
            if not loc:
                print(f"⚠️  '{stock}' 배열을 찾지 못함 — skip")
                skipped.append((stock, "array not found")); break
            const_pos, close_pos = loc
            segment = content[const_pos:close_pos]
            d, b, tp = str(e.get("date", "")), str(e.get("broker", "")), e.get("tp")
            dup = False
            for line in segment.splitlines():
                if (f"date:'{d}'" in line and f"broker:'{b}'" in line
                        and re.search(r"\btp:" + re.escape(js_val(tp)) + r"[,\s}]", line)):
                    dup = True; break
            if dup:
                skipped.append((stock, f"{d} {b} 중복")); continue
            before = content[:close_pos].rstrip()
            comma = "," if before.endswith("}") else ""
            content = before + comma + "\n    " + serialize(e) + ",\n  " + content[close_pos:]
            added.append((stock, d, b, tp))
            log_items.append({"stock": stock, "broker": b, "tp": tp, "entryDate": d})

    # ── 2. patch_last: 마지막 항목에 없는 분기 필드 보완 ──
    for stock, fields in (job.get("patch_last") or {}).items():
        loc = find_array(content, stock)
        if not loc:
            print(f"⚠️  '{stock}' 배열을 찾지 못함 — patch skip")
            skipped.append((stock, "array not found")); continue
        const_pos, close_pos = loc
        segment = content[const_pos:close_pos]
        lines = segment.splitlines()
        last_i = None
        for i in range(len(lines) - 1, -1, -1):
            if re.search(r"\{\s*date:'", lines[i]):
                last_i = i; break
        if last_i is None:
            skipped.append((stock, "엔트리 없음 — patch skip")); continue
        line = lines[last_i]
        missing = {k: v for k, v in fields.items() if f"{k}:" not in line and v is not None}
        if not missing:
            skipped.append((stock, "분기 필드 이미 존재")); continue
        extra = ", ".join(f"{k}:{js_val(v)}" for k, v in missing.items())
        trailing = "}," if line.rstrip().endswith("},") else "}"
        new_line = re.sub(r"\s*\},?\s*$", ", " + extra + " " + trailing, line)
        lines[last_i] = new_line
        content = content[:const_pos] + "\n".join(lines) + content[close_pos:]
        patched.append((stock, list(missing.keys())))
        log_items.append({"stock": stock, "broker": "분기컨센", "tp": None, "entryDate": today,
                          "note": "분기 컨센서스 보완 (" + ", ".join(f"{k}:{js_val(v)}" for k, v in missing.items()) + ")"})

    if not added and not patched:
        print("변경 없음 — 저장/커밋 불필요")
        for s in skipped:
            print("  skip:", s)
        return

    # ── 3. updateLog 갱신 (맨 앞에 오늘 블록, 이미 있으면 items 병합) ──
    def log_item_js(it):
        parts = [f"stock:'{it['stock']}'", f"broker:'{it['broker']}'",
                 f"tp:{js_val(it['tp'])}", f"entryDate:'{it['entryDate']}'"]
        if it.get("note"):
            parts.append(f"note:{js_val(it['note'])}")
        return "    { " + ", ".join(parts) + " },"

    ul_pos = content.find("const updateLog = [")
    if ul_pos >= 0 and log_items:
        head_end = content.find("\n", ul_pos) + 1
        m = re.match(r"(\s*\{ date: '" + re.escape(str(today)) + r"', items: \[\n)",
                     content[head_end:head_end + 200])
        items_js = "\n".join(log_item_js(it) for it in log_items)
        if m:
            ins = head_end + m.end(1)
            content = content[:ins] + items_js + "\n" + content[ins:]
        else:
            block = f"  {{ date: '{today}', items: [\n{items_js}\n  ]}},\n"
            content = content[:head_end] + block + content[head_end:]

    # ── 4. 검증: 이중콤마 + JS 문법 (실패 시 원본 유지) ──
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
    biggest = max(scripts, key=len)
    for i, l in enumerate(biggest.split("\n")):
        if ",," in l:
            print(f"❌ 이중 콤마 발견 (line {i+1}): {l.strip()[:100]} — 원본 유지, exit 1")
            sys.exit(1)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as t:
        t.write(biggest); tmp = t.name
    r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
    os.unlink(tmp)
    if r.returncode != 0:
        print("❌ JS 문법 오류 — 원본 유지, exit 1\n" + r.stderr[:500])
        sys.exit(1)

    with open(idx_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ 저장 완료 — 추가 {len(added)}건, 분기보완 {len(patched)}건, 스킵 {len(skipped)}건")
    for s, d, b, tp in added:
        print(f"  + {s} {d} {b} TP {tp}")
    for s, ks in patched:
        print(f"  ~ {s} 분기필드 {ks}")
    for s in skipped:
        print(f"  skip: {s}")

if __name__ == "__main__":
    main()
