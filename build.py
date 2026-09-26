#!/usr/bin/env python3
"""医学综合·冲刺刷题 —— 构建脚本
把 data/*.json 注入 template.html，产出单文件离线刷题系统 index.html。

依赖数据文件（由 tools/ 下脚本生成）：
  data/bank.json     题库（1317 题，含章节标签）
  data/similar.json  相似题 / 重复题 / 同题变体对比组
  data/memo.json     记忆型专项（数值、缩写代号）
  data/notes.json    复习资料考点手册
  data/meta.json     卷别、章节、答案分布统计

生成题库的完整链路：
  python3 tools/parse_bank.py     # 三份 md 题库 -> bank.json
  python3 tools/classify.py       # 按复习资料章节体系打标签
  python3 tools/parse_extras.py   # -> similar.json / memo.json / notes.json / meta.json
  python3 build.py                # -> index.html
"""
import os
import json
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

REQUIRED = ["bank.json", "similar.json", "memo.json", "notes.json", "meta.json"]


def load(name, required=True):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        if required:
            sys.exit("缺少数据文件 %s，请先运行 tools/ 下的生成脚本（见文件头说明）。" % path)
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    bank = load("bank.json")
    similar = load("similar.json")
    memo = load("memo.json")
    notes = load("notes.json")
    meta = load("meta.json")
    figs = load("figures.json", required=False) or []

    # 把插图挂到题目上（不写回 bank.json，避免解析管线重跑时被冲掉）
    figmap, attached, missed = {}, 0, []
    for f in figs:
        figmap[f["id"]] = {"d": f["d"], "cap": f.get("cap", "")}
        qk = f.get("q")
        keys = qk if isinstance(qk, list) else ([qk] if qk else [])
        for one in keys:
            hit = [q for q in bank if q["paper"] == one["paper"] and q["n"] == one["n"]
                   and q["type"] == one["type"]]
            if not hit:
                missed.append("%s -> 未匹配到题目 %s" % (f["id"], one))
                continue
            for q in hit:
                q["fig"] = f["id"]
            attached += 1
    if missed:
        print("⚠ 插图挂载告警：")
        for m in missed:
            print("   " + m)

    with open(os.path.join(BASE, "template.html"), encoding="utf-8") as f:
        tpl = f.read()

    missing = [k for k in ("__BANK_DATA__", "__SIMILAR_DATA__", "__MEMO__", "__NOTES__", "__TOTAL__",
                           "__SINGLE_COUNT__", "__MULTI_COUNT__", "__SIMILAR_COUNT__",
                           "__A_COUNT__", "__B_COUNT__", "__FIGURES__",
                           "__PAPERS__", "__CATS__", "__CHEAT__") if k not in tpl]
    if missing:
        sys.exit("模板缺少占位符：%s" % "、".join(missing))

    j = lambda o: json.dumps(o, ensure_ascii=False)
    html = (tpl
            .replace("__BANK_DATA__", j(bank))
            .replace("__SIMILAR_DATA__", j(similar))
            .replace("__MEMO__", j(memo))
            .replace("__NOTES__", j(notes))
            .replace("__FIGURES__", j(figmap))
            .replace("__PAPERS__", j(meta["papers"]))
            .replace("__CATS__", j(meta["cats"]))
            .replace("__CHEAT__", j(meta["cheat"]))
            .replace("__TOTAL__", str(meta["total"]))
            .replace("__SINGLE_COUNT__", str(meta["single"]))
            .replace("__MULTI_COUNT__", str(meta["multi"]))
            .replace("__A_COUNT__", str(meta["a"]))
            .replace("__B_COUNT__", str(meta["b"]))
            .replace("__SIMILAR_COUNT__", str(len(similar))))

    out = os.path.join(BASE, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    kb = os.path.getsize(out) / 1024.0
    print("生成完成：%s（%.0f KB）" % (out, kb))
    print("题库：%d 题（A 型 %d + B 型 %d + X 型 %d）"
          % (meta["total"], meta["cheat"]["na"], meta["cheat"]["nb"], meta["cheat"]["nx"]))
    print("相似题对比组：%d 组" % len(similar))
    print("记忆型专项：数值 %d 题 / 缩写 %d 题" % (len(memo["num"]), len(memo["latin"])))
    print("复习资料：%d 部分 / %d 考点" % (len(notes), sum(n["n"] for n in notes)))
    print("章节分类：%d 类 ｜ 套卷：%d 套" % (len(meta["cats"]), len(meta["papers"])))
    if figs:
        fkb = sum(f["kb"] for f in figs)
        print("题目插图：%d 张（%.2f MB，已内联）· 已挂到 %d 道题" % (len(figs), fkb / 1024.0, attached))
    else:
        print("题目插图：无（figures.json 不存在或为空）")
    left = html.count("__") and [x for x in ("__BANK_DATA__", "__SIMILAR_DATA__", "__MEMO__",
                                             "__NOTES__", "__FIGURES__", "__PAPERS__", "__CATS__",
                                             "__CHEAT__", "__TOTAL__", "__SINGLE_COUNT__",
                                             "__MULTI_COUNT__", "__A_COUNT__", "__B_COUNT__",
                                             "__SIMILAR_COUNT__") if x in html]
    print("占位符残留检查：%s" % ("通过" if not left else "仍有残留 %s" % left))


if __name__ == "__main__":
    main()
