#!/usr/bin/env python3
"""生成派生数据：similar.json（相似题对比组）、notes.json（复习资料）、meta.json（卷别/章节/答案分布统计）

依赖 data/bank.json（先跑 tools/parse_bank.py 与 tools/classify.py）。
"""
import re
import os
import json
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
SRC_NOTES = os.path.join(BASE, "source", "医学综合复习资料（仅供参考）.md")

PART_SHORT = {
    "人体解剖学": "解剖学",
    "生理学": "生理学",
    "内科学基础（诊断学）": "内科学基础",
    "外科学（外科总论）": "外科学",
}
PART_ORDER = ["人体解剖学", "生理学", "内科学基础（诊断学）", "外科学（外科总论）"]
PART_NO = {"人体解剖学": "第一部分", "生理学": "第二部分",
           "内科学基础（诊断学）": "第三部分", "外科学（外科总论）": "第四部分"}

bank = json.load(open(os.path.join(DATA, "bank.json"), encoding="utf-8"))
by_key = {(q["paper"], q["n"]): q for q in bank}
by_id = {q["id"]: q for q in bank}


def q_order(name):
    """卷别排序键：真题按年份升序，模拟卷排最后。"""
    m = re.match(r"^(\d{4})年真题$", name)
    return int(m.group(1)) if m else 3000


# ============================================================ 1) 相似题对比
RE_REF = re.compile(r"与\s*[「]?\s*(.+?)第\s*(\d+)\s*题")
RE_SIM = re.compile(r"相似度\s*(\d+)\s*%")

groups, seen, missed = [], set(), []
for q in bank:
    for t in q["tags"]:
        m = RE_REF.search(t["text"])
        if not m:
            missed.append(t["text"])
            continue
        ref_paper, ref_n = m.group(1).strip(), int(m.group(2))
        other = by_key.get((ref_paper, ref_n))
        if other is None:
            missed.append("%s第%d题 -> 未找到 %s第%d题" % (q["paper"], q["n"], ref_paper, ref_n))
            continue
        key = frozenset((q["id"], other["id"]))
        if key in seen:
            continue
        seen.add(key)
        sm = RE_SIM.search(t["text"])
        note = re.sub(r"^[^\u4e00-\u9fff]*", "", t["text"]).strip()
        a, b = (q, other) if q["id"] < other["id"] else (other, q)
        title = "%s第%d题 ↔ %s第%d题" % (a["paper"], a["n"], b["paper"], b["n"])
        if sm:
            title += "（题干相似度 %s%%）" % sm.group(1)
        if a["cat"] == b["cat"]:
            title = a["cat"] + " · " + title
        groups.append({
            "kind": t["kind"],
            "type": "【对比 %d】" % (len(groups) + 1),
            "title": title,
            "sim": int(sm.group(1)) if sm else 0,
            "note": note,
            "lines": [["A", a["s"], a], ["B", b["s"], b]],
            "ans_list": [a["a"], b["a"]],
            "diff": note,
            "variant": "",
            "shared_ans": "",
        })

kind_count = Counter(g["kind"] for g in groups)
json.dump(groups, open(os.path.join(DATA, "similar.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("相似题对比组：%d 组（%s）" % (len(groups), dict(kind_count)))
if missed:
    print("  未配对：%d" % len(missed))
    for x in missed[:5]:
        print("    ", x)

# ============================================================ 1b) 记忆型专项
# 医学综合题库中没有纪年题，故「纯记忆」按两条口径重新界定：
#   数值类：需要硬记的数值与单位（ml / mmHg / mmol / 次分 / ℃ …）
#   缩写类：题干含英文字母代号的医学术语（pH、APTT、QRS、FEV₁/FVC、ARDS …）
RE_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9\u2080-\u2089\u207b\u207a]{1,}")
RE_UNIT = re.compile(r"\d+(?:\.\d+)?\s*(?:ml|mL|mmHg|mmol|kPa|mg|kg|dB|Hz|次/分|U/L|℃|/L)")


def mini(q):
    return {"n": q["n"], "type": q["type"], "paper": q["paper"], "multi": q["multi"],
            "s": q["s"], "o": q["o"], "a": q["a"]}


memo_abbr, memo_num = [], []
for q in bank:
    stem = q["s"]
    toks = {m.group(0) for m in RE_LATIN.finditer(stem)}
    toks = {t for t in toks if len(t) >= 2 and any(c.isupper() for c in t)}
    if toks:
        memo_abbr.append(q)
    elif RE_UNIT.search(stem + " " + " ".join(o["t"] for o in q["o"])):
        memo_num.append(q)

json.dump({"year": [], "num": [mini(q) for q in memo_num], "latin": [mini(q) for q in memo_abbr]},
          open(os.path.join(DATA, "memo.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("记忆型专项：数值类 %d 题 / 缩写代号类 %d 题" % (len(memo_num), len(memo_abbr)))

# ============================================================ 2) 复习资料
def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


with open(SRC_NOTES, encoding="utf-8") as f:
    lines = f.read().split("\n")
part = chap = ""
blocks = []          # [(part, chap, {pt, tx})]
cur = None
fence = False
code = []
for ln in lines:
    s = ln.rstrip()
    if s.strip().startswith("```"):
        fence = not fence
        if not fence and cur is not None:
            # 代码块是骨骼/血管的组成树，保留缩进与框线，用等宽块呈现
            cur["tx"].append(("h", '<div class="lec-code">%s</div>' % esc("\n".join(code))))
            code = []
        continue
    if fence:
        code.append(s)
        continue
    mp = re.match(r"^#\s+第.部分\s*(.+)$", s)
    if mp:
        part, chap, cur = mp.group(1).strip(), "", None
        continue
    mc = re.match(r"^##\s+(第.+章)\s*(.*)$", s)
    if mc:
        chap = (mc.group(1) + mc.group(2)).strip()
        cur = None
        continue
    mk = re.match(r"^###\s+(考点\s*\d+)\s*(.*)$", s)
    if mk and chap:
        cur = {"pt": (mk.group(1) + mk.group(2)).strip(), "tx": []}
        blocks.append((part, chap, cur))
        continue
    if cur is None or not s:
        continue
    if s.startswith(">"):
        continue
    if s.startswith("*") and s.endswith("*") and len(s) > 2:
        # 「*图1-1上肢骨的组成*」这类图注：转成淡色小字
        cur["tx"].append(("h", '<div style="font-size:12px;color:var(--muted);margin:-2px 0 10px">%s</div>'
                          % esc(s.strip("*").strip())))
    elif not s.startswith("#"):
        cur["tx"].append(("t", s.strip()))


def render_tx(tx):
    """把 (类型, 内容) 序列拼成 HTML：连续正文合并成一个 <p>"""
    out, buf = [], []
    for kind, val in tx:
        if kind == "t":
            buf.append(val)
        else:
            if buf:
                out.append("<p>%s</p>" % esc(" ".join(buf)))
                buf = []
            out.append(val)
    if buf:
        out.append("<p>%s</p>" % esc(" ".join(buf)))
    return "".join(out)

bank_cat = Counter(q["cat"] for q in bank)
notes = []
for p in PART_ORDER:
    chaps = []
    seen_c = set()
    for bp, bc, blk in blocks:
        if bp != p:
            continue
        if bc not in seen_c:
            seen_c.add(bc)
            chaps.append({"name": bc, "pts": []})
        chaps[-1]["pts"].append(blk)
    chaps = [c for c in chaps if c["pts"]]
    if not chaps:
        continue
    npts = sum(len(c["pts"]) for c in chaps)
    short = PART_SHORT[p]
    body = ["<h2>%s %s</h2>" % (esc(PART_NO[p]), esc(p)),
            "<blockquote>共 %d 章 / %d 个考点 · 摘自《医学综合复习资料（仅供参考）》，以原书为准</blockquote>"
            % (len(chaps), npts)]
    for c in chaps:
        clean = re.sub(r"^第.{1,3}章\s*", "", c["name"])
        catkey = short + "·" + clean
        cnt = bank_cat.get(catkey, 0)
        cnt_txt = ("<span style=\"font-weight:400;color:var(--muted)\">（题库 %d 题）</span>" % cnt) if cnt else ""
        body.append('<div class="lec-sec-head"><h3>%s %s</h3>%s</div>' % (
            esc(c["name"]), cnt_txt,
            ('<button class="lec-practice" onclick="event.stopPropagation();startCat(\'%s\')">练习本章</button>' % catkey)
            if cnt else ""))
        for blk in c["pts"]:
            body.append("<p><b>%s</b></p>%s" % (esc(blk["pt"]), render_tx(blk["tx"])))
    notes.append({
        "id": "p%d" % (len(notes) + 1),
        "no": PART_NO[p],
        "title": p,
        "dur": "%d 章 · %d 考点" % (len(chaps), npts),
        "n": npts,
        "body": "\n".join(body),
    })

json.dump(notes, open(os.path.join(DATA, "notes.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("复习资料卡片：%d 张（%s）" % (len(notes), " / ".join("%s %d考点" % (n["title"], n["n"]) for n in notes)))

# ============================================================ 3) 统计
# 卷别
papers = []
for name in sorted({q["paper"] for q in bank}, key=lambda x: (q_order(x), x)):
    qs = [q for q in bank if q["paper"] == name]
    papers.append({
        "name": name,
        "count": len(qs),
        "a": sum(1 for q in qs if q["type"] == "A"),
        "b": sum(1 for q in qs if q["type"] == "B"),
        "x": sum(1 for q in qs if q["type"] == "X"),
    })

# 章节
cats = [{"name": k, "count": v} for k, v in bank_cat.most_common()]

# 答案分布
single = [q for q in bank if not q["multi"]]
multi = [q for q in bank if q["multi"]]
sc = Counter(q["a"] for q in single)
tot_s = max(1, len(single))
singles = [{"k": k, "n": sc.get(k, 0), "pct": round(sc.get(k, 0) * 100.0 / tot_s, 1)}
           for k in "ABCDE"]
ml = Counter(len(q["a"]) for q in multi)
tot_m = max(1, len(multi))
multis = [{"k": k, "n": ml.get(k, 0), "pct": round(ml.get(k, 0) * 100.0 / tot_m, 1)}
          for k in sorted(ml)]

# 单选题各选项被选中的比例（含干扰项）
opt_hit = Counter()
for q in single:
    for o in q["o"]:
        if o["k"] in q["a"]:
            opt_hit[o["k"]] += 1
best = max(singles, key=lambda x: x["n"])
worst = min(singles, key=lambda x: x["n"])
top_multi = max(multis, key=lambda x: x["n"])
allsel = ml.get(5, 0)
tip = (
    "① 单选题（A/B 型）：答案落点分布 "
    + "、".join("%s %d 题(%.1f%%)" % (s["k"], s["n"], s["pct"]) for s in singles)
    + "。最高的是 %s，最低的是 %s，差距不大，说明本库没有明显可蒙的选项，靠积累比靠技巧可靠。"
    % (best["k"], worst["k"])
    + "② 多选题（X 型）：正确项以 %d 个居多（%d 题，%.1f%%）；五项全对的有 %d 题（%.1f%%），"
    % (top_multi["k"], top_multi["n"], top_multi["pct"], allsel,
       round(allsel * 100.0 / tot_m, 1))
    + "所以「不会就全选」并不划算，先排除明显错误项，再按 2～3 个作答命中率更高。"
    + "③ 配伍题（B 型）：一组 5 个备选项对应其下 2 道小题，同一选项可被同组小题各选一次；"
      "拿到题先看共用选项，再逐个小题排除，比孤立地读题干快得多。"
    + "④ 通用策略：先在答题卡上把所有会做的题做完，再回头攻不确定的；多选题少选不得分，"
      "犹豫的选项先划掉再决定，不要空题。"
)

meta = {
    "papers": papers,
    "cats": cats,
    "cheat": {
        "tip": tip,
        "na": sum(1 for q in bank if q["type"] == "A"),
        "nb": sum(1 for q in bank if q["type"] == "B"),
        "nx": sum(1 for q in bank if q["type"] == "X"),
        "singles": singles,
        "multis": multis,
    },
    "total": len(bank),
    "single": len(single),
    "multi": len(multi),
    "a": sum(1 for q in bank if q["type"] == "A"),
    "b": sum(1 for q in bank if q["type"] == "B"),
}
json.dump(meta, open(os.path.join(DATA, "meta.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("卷别：%d 套 ｜ 章节：%d 类" % (len(papers), len(cats)))
print("单选答案落点：%s" % "、".join("%s:%d" % (s["k"], s["n"]) for s in singles))
print("多选正确项个数：%s" % "、".join("%d个:%d" % (m["k"], m["n"]) for m in multis))
print("已写出 data/similar.json / data/notes.json / data/meta.json")
