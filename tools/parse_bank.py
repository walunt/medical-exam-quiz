#!/usr/bin/env python3
"""医学综合题库解析器 —— 三份 md 题库 -> data/bank.json

输入（source/ 目录）：
  单选题（A型题）_真题+模拟题.md   五选一
  多选题（X型题）_真题+模拟题.md   多选
  配伍单选题（B型题）_真题+模拟题.md  共用备选项 + 多个小题

输出统一结构（每题）：
  id      全局唯一序号
  n       原卷题号
  type    A / X / B
  paper   卷别（2014年真题 / 模拟题（一） / ...）
  s       题干
  o       选项 [{k,t}]
  a       答案（"B" / "ABD"）
  multi   是否多选
  exp     {base: 原卷【解析】, ai: 【AI解析】}
  tags    [{kind, text}] 相似题/重复题/同题变体标注
  grp     B型题所属组标签（A/X 为 None）
  shared  B型题是否共用备选项
"""
import re
import os
import json
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "source")
OUT = os.path.join(BASE, "data")

FILES = [
    ("单选题（A型题）_真题+模拟题.md", "A"),
    ("多选题（X型题）_真题+模拟题.md", "X"),
    ("配伍单选题（B型题）_真题+模拟题.md", "B"),
]

RE_PAPER = re.compile(r"^##\s+(.+?)\s*$")
RE_QHEAD = re.compile(r"^###\s+第\s*(\d+)\s*题\s*$")
RE_BGRP = re.compile(r"^###\s+第\s*(\d+)\s*组（第\s*([\d～~\-]+)\s*题\s*·\s*(.+?)）\s*$")
RE_BSUB = re.compile(r"^\*\*第\s*(\d+)\s*题\*\*\s*[：:]\s*(.*)$")
RE_STEM = re.compile(r"^\*\*【题干】\*\*\s*(.*)$")
RE_ANS = re.compile(r"^\*\*【答案】\*\*\s*(.*)$")
RE_EXP = re.compile(r"^\*\*【解析】\*\*\s*(.*)$")
RE_AIEXP = re.compile(r"^\*\*【AI解析】\*\*\s*(.*)$")
RE_SHARED = re.compile(r"^\*\*【共用备选答案】\*\*\s*$")
RE_OPT = re.compile(r"^([A-E])\s*[.、．]\s*(.*)$")
RE_TAG = re.compile(r"^>\s*(.*)$")
RE_TAGKIND = re.compile(r"\*\*(相似题|重复题|同题变体)\*\*")
RE_LETTERS = re.compile(r"[A-E]")
# 溯源标记：扫描件缺字后由 AI 补齐的内容，混在选项文本里
RE_AIMARK = re.compile(r"\s*`?\s*[（(]\s*AI\s*推测[^）)]*[）)]`?")
# 原卷插图引用（Markdown 图片语法），图未收录
RE_IMGREF = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def scrub_text(s, flags):
    """剥离溯源标记与图片引用，同时记录该题的数据提示。"""
    if RE_AIMARK.search(s):
        flags.add("部分内容为扫描件缺字后由 AI 补齐，请以原卷为准")
        s = RE_AIMARK.sub("", s)
    if RE_IMGREF.search(s):
        flags.add("原卷附有插图，本系统未收录图片，本题仅凭文字作答")
        s = RE_IMGREF.sub("", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def scrub(q):
    flags = set()
    q["s"] = scrub_text(q["s"], flags)
    for o in q["o"]:
        o["t"] = scrub_text(o["t"], flags)
    if flags:
        q["flag"] = "；".join(sorted(flags))
    else:
        q["flag"] = ""
    return q


# ---------------------------------------------------------------- 基础工具
def read(fn):
    with open(os.path.join(SRC, fn), encoding="utf-8") as f:
        return f.read()


def split_blocks(text):
    """按 ### 切块，同时跟踪当前 ## 卷别标题。返回 [(header, paper, [lines])]"""
    paper = ""
    cur = None
    blocks = []
    for ln in text.split("\n"):
        if ln.startswith("### "):
            if cur:
                blocks.append(cur)
            cur = [ln.rstrip(), paper, []]
            continue
        if ln.startswith("## ") and cur is None:
            m = RE_PAPER.match(ln)
            if m:
                paper = m.group(1)
            continue
        if ln.startswith("## ") and cur is not None:
            if cur:
                blocks.append(cur)
            m = RE_PAPER.match(ln)
            paper = m.group(1) if m else paper
            cur = None
            continue
        if cur is not None:
            cur[2].append(ln)
    if cur:
        blocks.append(cur)
    # 丢弃空块
    return [b for b in blocks if any(x.strip() for x in b[2])]


def _add(tag_lines, mode, text):
    """把续行追加到当前字段"""
    text = text.strip()
    if not text:
        return
    tag_lines[mode].append(text)


def parse_ax(lines, paper, qtype):
    """解析 A 型题 / X 型题块"""
    f = {"stem": [], "ans": [], "exp": [], "ai": [], "tag": []}
    opts = []
    seen = set()
    mode = None
    dup = 0
    for ln in lines:
        s = ln.rstrip()
        if not s.strip():
            continue
        m = RE_STEM.match(s)
        if m:
            mode = "stem"
            f["stem"].append(m.group(1).strip())
            continue
        m = RE_ANS.match(s)
        if m:
            mode = "ans"
            f["ans"].append(m.group(1).strip())
            continue
        m = RE_AIEXP.match(s)
        if m:
            mode = "ai"
            f["ai"].append(m.group(1).strip())
            continue
        m = RE_EXP.match(s)
        if m:
            mode = "exp"
            f["exp"].append(m.group(1).strip())
            continue
        m = RE_TAG.match(s)
        if m:
            mode = "tag"
            f["tag"].append(m.group(1).strip())
            continue
        m = RE_OPT.match(s)
        if m and mode in ("ans", "opt"):
            k, t = m.group(1), m.group(2).strip()
            if k in seen:
                dup += 1
                continue
            seen.add(k)
            opts.append({"k": k, "t": t})
            mode = "opt"
            continue
        # 续行
        if mode in ("stem", "ans", "exp", "ai", "tag"):
            f[mode].append(s.strip())
    return build_q(f, opts, paper, qtype, dup)


def parse_b(lines, header, paper):
    """解析 B 型题块（共用备选项 + 多个小题）"""
    gm = RE_BGRP.match(header)
    if not gm:
        return []
    gno, rng, bpaper = gm.group(1), gm.group(2), gm.group(3).strip()
    grp_label = "第 %s 组" % gno

    # 切出共用选项区与各小题
    shared_opts = []
    subs = []
    cur = None
    in_shared = False
    for ln in lines:
        s = ln.rstrip()
        if RE_SHARED.match(s):
            in_shared = True
            continue
        m = RE_BSUB.match(s)
        if m:
            cur = {"n": int(m.group(1)), "lines": [m.group(2)]}
            subs.append(cur)
            in_shared = False
            continue
        if cur is None:
            if in_shared:
                om = RE_OPT.match(s)
                if om:
                    shared_opts.append({"k": om.group(1), "t": om.group(2).strip()})
            continue
        cur["lines"].append(s)

    out = []
    for sub in subs:
        f = {"stem": [], "ans": [], "exp": [], "ai": [], "tag": []}
        mode = "stem"
        for s in sub["lines"]:
            if not s.strip():
                continue
            m = RE_AIEXP.match(s)
            if m:
                mode = "ai"
                f["ai"].append(m.group(1).strip())
                continue
            m = RE_EXP.match(s)
            if m:
                mode = "exp"
                f["exp"].append(m.group(1).strip())
                continue
            m = RE_ANS.match(s)
            if m:
                mode = "ans"
                f["ans"].append(m.group(1).strip())
                continue
            m = RE_TAG.match(s)
            if m:
                mode = "tag"
                f["tag"].append(m.group(1).strip())
                continue
            f[mode].append(s.strip())
        q = build_q(f, [dict(o) for o in shared_opts], bpaper, "B", 0)
        q["n"] = sub["n"]
        q["grp"] = grp_label
        q["shared"] = True
        out.append(q)
    return out


def build_q(f, opts, paper, qtype, dup):
    stem = " ".join(f["stem"]).strip()
    ans_raw = " ".join(f["ans"])
    letters = RE_LETTERS.findall(ans_raw)
    ans = "".join(dict.fromkeys(letters))
    tags = []
    for t in f["tag"]:
        km = RE_TAGKIND.search(t)
        if not km:
            if tags:
                tags[-1]["text"] += " " + t
            continue
        tags.append({"kind": km.group(1), "text": t})
    return {
        "n": 0,
        "type": qtype,
        "paper": paper,
        "s": stem,
        "o": opts,
        "a": ans,
        "multi": qtype == "X" or len(ans) > 1,
        "exp": {"base": " ".join(f["exp"]).strip(), "ai": " ".join(f["ai"]).strip()},
        "tags": tags,
        "grp": None,
        "shared": False,
        "_dup": dup,
    }


# ---------------------------------------------------------------- 主流程
def main():
    bank = []
    report = {"blocks": {}, "issues": [], "by_type": Counter(), "by_paper": Counter()}

    for fn, qtype in FILES:
        text = read(fn)
        blocks = split_blocks(text)
        n_ax = n_b = 0
        for header, paper, lines in blocks:
            if RE_BGRP.match(header):
                qs = parse_b(lines, header, paper)
                bank.extend(qs)
                n_b += len(qs)
            elif RE_QHEAD.match(header):
                m = RE_QHEAD.match(header)
                q = parse_ax(lines, paper, qtype)
                q["n"] = int(m.group(1))
                bank.append(q)
                n_ax += 1
        report["blocks"][qtype] = {"块数": len(blocks), "A/X题数": n_ax, "B小题数": n_b}

    # 全局编号 + 校验
    for i, q in enumerate(bank):
        q["id"] = i
        report["by_type"][q["type"]] += 1
        report["by_paper"][q["paper"] or "(无卷别)"] += 1
        issues = []
        if not q["s"]:
            issues.append("题干为空")
        if len(q["o"]) < 4:
            issues.append("选项不足（%d 项）" % len(q["o"]))
        if not q["a"]:
            issues.append("答案为空")
        else:
            ks = {o["k"] for o in q["o"]}
            missing = [c for c in q["a"] if c not in ks]
            if missing:
                issues.append("答案 %s 不在选项中" % "".join(missing))
        if q["_dup"]:
            issues.append("选项行重复 %d 行（已按首现保留）" % q["_dup"])
        if not q["exp"]["ai"]:
            issues.append("缺 AI 解析")
        if q["type"] == "B" and len(q["o"]) < 5:
            issues.append("共用选项不足")
        if issues:
            report["issues"].append({
                "type": q["type"], "paper": q["paper"], "n": q["n"],
                "grp": q["grp"], "问题": "；".join(issues),
                "题干": q["s"][:40],
            })

    for q in bank:
        q.pop("_dup", None)
        scrub(q)

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "bank.json"), "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=1)

    # 报告
    print("=" * 66)
    print("题库解析报告")
    print("=" * 66)
    print("总题数：%d" % len(bank))
    for t in ("A", "X", "B"):
        print("  %s 型题：%d" % (t, report["by_type"][t]))
    print("单选：%d  多选：%d" % (sum(1 for q in bank if not q["multi"]),
                                  sum(1 for q in bank if q["multi"])))
    print("-" * 66)
    print("卷别分布：")
    for k, v in sorted(report["by_paper"].items()):
        print("  %-14s %4d" % (k, v))
    print("-" * 66)
    print("块统计：")
    for k, v in report["blocks"].items():
        print("  %s  %s" % (k, v))
    print("-" * 66)
    print("相似/重复标注：%d 处" % sum(len(q["tags"]) for q in bank))
    print("有解析(原卷)：%d 题   有 AI 解析：%d 题" % (
        sum(1 for q in bank if q["exp"]["base"]),
        sum(1 for q in bank if q["exp"]["ai"])))
    print("-" * 66)
    print("数据质量问题：%d 处" % len(report["issues"]))
    for it in report["issues"]:
        print("  [%s] %s %s 题%s -> %s  | %s" % (
            it["type"], it["paper"], it["n"],
            ("(%s)" % it["grp"]) if it["grp"] else "",
            it["问题"], it["题干"]))
    flagged = [q for q in bank if q["flag"]]
    report["flagged"] = [{"paper": q["paper"], "n": q["n"], "type": q["type"],
                          "flag": q["flag"]} for q in flagged]
    print("-" * 66)
    print("带数据提示的题：%d 题（已标注，界面会提示）" % len(flagged))
    detail = Counter(f for q in flagged for f in q["flag"].split("；"))
    for k, v in detail.most_common():
        print("  %3d 题  %s" % (v, k))
    with open(os.path.join(OUT, "parse_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print("\n已写出 data/bank.json 与 data/parse_report.json")


if __name__ == "__main__":
    main()
