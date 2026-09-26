#!/usr/bin/env python3
"""知识点分类器 —— 依据《医学综合复习资料》的四大部分 / 38 章 / 307 考点体系，
给 data/bank.json 中每道题打章节标签。

算法（两级判定）：
  第 1 级：在「人体解剖学 / 生理学 / 内科学基础 / 外科学」四大部分之间分类。
           解剖学与生理学存在同名章节（感觉器官、中枢神经系统），
           先定部分可彻底消除跨部分串台。
  第 2 级：在已选定的部分内部选章节（章节集合互斥，不再有歧义）。

相似度用中文二元组 TF-IDF 余弦；考点标题加权 3 倍；另叠加人工锚点词表，
锚点可指定所属部分以增强判别力。章节规模做过惩罚，避免大章节垄断。

输出字段：
  cat1  部分标签（解剖学 / 生理学 / 内科学基础 / 外科学）
  cat   章节标签（如「解剖学·骨学」）
  conf  置信度
  alt   次优章节（供人工复核）
"""
import re
import os
import json
import math
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "source", "医学综合复习资料（仅供参考）.md")
BANK = os.path.join(BASE, "data", "bank.json")

HAN = re.compile(r"[\u4e00-\u9fff]+")

PART_SHORT = {
    "人体解剖学": "解剖学",
    "生理学": "生理学",
    "内科学基础（诊断学）": "内科学基础",
    "外科学（外科总论）": "外科学",
}
SHORT_PARTS = list(PART_SHORT.values())


def han_only(s):
    return "".join(HAN.findall(s))


def bigrams(s):
    s = han_only(s)
    return [s[i:i + 2] for i in range(len(s) - 1)] if len(s) > 1 else ([s] if s else [])


# ------------------------------------------------------------ 解析复习资料
def load_points():
    with open(SRC, encoding="utf-8") as f:
        lines = f.read().split("\n")
    part = chap = ""
    out, cur_title, buf = [], None, []
    for ln in lines:
        s = ln.rstrip()
        mp = re.match(r"^#\s+第.部分\s*(.+)$", s)
        if mp:
            if cur_title:
                out.append((part, chap, cur_title, " ".join(buf)))
            part, chap, cur_title, buf = mp.group(1).strip(), "", None, []
            continue
        mc = re.match(r"^##\s+(第.+章)\s*(.*)$", s)
        if mc:
            if cur_title:
                out.append((part, chap, cur_title, " ".join(buf)))
            chap = (mc.group(1) + mc.group(2)).strip()
            cur_title, buf = None, []
            continue
        mk = re.match(r"^###\s+(考点\s*\d+)\s*(.*)$", s)
        if mk:
            if cur_title:
                out.append((part, chap, cur_title, " ".join(buf)))
            cur_title = (mk.group(1) + mk.group(2)).strip()
            buf = []
            continue
        if cur_title is not None and s and not s.startswith(("#", ">", "|", "-", "*")):
            buf.append(s)
    if cur_title:
        out.append((part, chap, cur_title, " ".join(buf)))
    return [p for p in out if p[1] and p[3].strip()]


# ------------------------------------------------------------ 人工锚点词表
# (关键词, 章节关键词, 限定部分或 None, 权重)
A = [
    # ===== 人体解剖学 =====
    (["椎骨", "棘突", "椎体", "椎弓", "肋骨", "胸骨", "颅骨", "肱骨", "股骨", "胫骨", "腓骨", "髋骨", "骨性", "骨学", "囟", "眶"], "骨学", "人体解剖学", 5),
    (["关节", "韧带", "关节囊", "半月板", "椎间盘", "关节盘", "关节面", "关节唇", "肩关节", "髋关节", "膝关节", "肘关节", "颞下颌"], "关节学", "人体解剖学", 5),
    (["肌的", "肌肉", "扁肌", "胸锁乳突肌", "臀大肌", "三角肌", "肌学", "肌腱", "膈肌", "肌群", "肌收缩时"], "肌学", "人体解剖学", 5),
    (["胃", "小肠", "大肠", "十二指肠", "空肠", "回肠", "结肠", "直肠", "肝", "胆囊", "胆管", "胰", "食管", "阑尾", "腹膜", "舌", "咽", "肛管", "齿状线"], "消化系统", "人体解剖学", 4),
    (["气管", "支气管", "肺", "胸膜", "喉", "纵隔", "肺泡", "声门", "前庭裂", "肺段"], "呼吸系统", "人体解剖学", 5),
    (["肾", "输尿管", "膀胱", "肾单位", "女性尿道", "尿道"], "泌尿系统", "人体解剖学", 5),
    (["女性尿道", "尿道内口"], "泌尿系统", "人体解剖学", 6),
    (["前列腺", "精囊", "睾丸", "附睾", "输精管", "阴囊", "阴茎", "男性尿道"], "男性生殖系统", "人体解剖学", 5),
    (["子宫", "卵巢", "输卵管", "阴道前庭", "阴道", "会阴", "乳房"], "女性生殖系统", "人体解剖学", 5),
    (["动脉", "静脉", "毛细血管", "淋巴", "胸导管", "乳糜池", "门静脉", "大隐静脉", "主动脉", "颈总动脉", "心传导系", "冠状"], "脉管系统", "人体解剖学", 4),
    (["眼球壁", "角膜", "巩膜", "虹膜", "睫状体", "鼓膜", "中耳", "内耳", "咽鼓管", "听小骨", "前庭器", "耳廓", "壶腹", "位觉斑", "螺旋器", "耳蜗"], "感觉器官", "人体解剖学", 5),
    (["脑神经", "脊神经", "神经丛", "臂丛", "腰丛", "骶丛", "交感干", "周围神经", "神经干", "脊神经节", "颅神经"], "周围神经系统", "人体解剖学", 5),
    (["脑室", "脑膜", "蛛网膜", "脑脊液", "内囊", "脑干", "小脑", "大脑皮质分区", "脊髓节段", "侧脑室", "硬膜", "传导束"], "中枢神经系统", "人体解剖学", 5),
    # ===== 生理学 =====
    (["内环境", "稳态", "负反馈", "正反馈", "反馈控制", "调节方式", "自身调节"], "绪论", "生理学", 6),
    (["静息电位", "动作电位", "锋电位", "钠泵", "兴奋性", "阈电位", "去极化", "复极化", "跨膜信号", "主动转运", "易化扩散", "单纯扩散", "横桥", "肌小节", "终板电位", "神经肌接头", "兴奋收缩耦联", "载体"], "细胞的基本功能", "生理学", 6),
    (["血浆", "血细胞", "红细胞", "白细胞", "血小板", "血型", "凝血", "血液凝固", "血浆渗透压", "血红蛋白", "交叉配血", "血沉", "血细胞比容", "纤维蛋白"], "血液", "生理学", 6),
    (["心输出量", "心动周期", "血压", "心率", "心音", "心电图", "窦房结", "房室结", "浦肯野", "心肌", "微循环", "每搏输出量", "前负荷", "心脏射血", "动脉血压", "中心静脉压", "颈动脉窦"], "血液循环", "生理学", 5),
    (["肺活量", "潮气量", "肺通气", "肺换气", "气体交换", "呼吸中枢", "血氧", "二氧化碳运输", "胸膜腔内压", "肺泡表面活性物质", "呼吸节律", "通气", "氧解离曲线"], "呼吸", "生理学", 5),
    (["胃液", "胃酸", "胰液", "胆汁", "小肠运动", "胃排空", "消化和吸收", "唾液", "胃肠激素", "胃蛋白酶", "维生素B12", "铁的吸收", "胃运动", "分节运动", "集团蠕动", "容受性舒张", "胃肠运动", "胃的运动", "移行性复合运动", "吸收的机制"], "消化和吸收", "生理学", 5),
    (["基础代谢率", "体温", "能量代谢", "散热", "产热", "特殊动力", "呼吸商"], "能量代谢和体温", "生理学", 6),
    (["肾小球滤过", "肾小管", "集合管", "尿液", "抗利尿激素", "肾糖阈", "水利尿", "醛固酮", "滤过率", "重吸收", "渗透压感受器", "清除率", "排尿反射", "内髓", "髓袢"], "肾脏的排泄", "生理学", 6),
    (["激素", "甲状腺", "胰岛素", "胰高血糖素", "肾上腺", "生长激素", "腺垂体", "神经垂体", "月经周期", "甲状旁腺激素", "降钙素", "糖皮质激素", "下丘脑调节肽", "促激素", "激素的作用机制"], "内分泌", "生理学", 5),
    (["视锥细胞", "视杆细胞", "暗适应", "明适应", "色觉", "感光换能", "视力", "视野", "声波传导", "耳蜗微音", "行波理论", "眼调节", "近视", "瞳孔对光反射"], "感觉器官", "生理学", 6),
    (["突触传递", "神经递质", "突触后电位", "感觉投射", "特异投射", "非特异投射", "牵张反射", "腱反射", "肌紧张", "大脑皮质功能", "条件反射", "诱发电位", "交感", "副交感", "内脏痛", "牵涉痛"], "中枢神经系统", "生理学", 5),
    # ===== 内科学基础 =====
    (["问诊", "主诉", "现病史", "既往史", "家族史", "个人史"], "问诊", "内科学基础（诊断学）", 6),
    (["发热", "疼痛", "咳嗽", "咯血", "呼吸困难", "发绀", "紫绀", "黄疸", "水肿", "恶心", "呕吐", "呕血", "便血", "晕厥", "意识障碍", "心悸", "腹泻", "惊厥", "蜘蛛痣", "紫癜", "肝浊音界消失"], "临床常见症状", "内科学基础（诊断学）", 4),
    (["视诊", "触诊", "叩诊", "听诊", "嗅诊", "淋巴结检查", "浅反射", "深反射", "病理反射", "脑膜刺激征", "心界", "肺下界", "肝浊音界", "腹部触诊", "体型", "面容", "体位"], "体格检查", "内科学基础（诊断学）", 4),
    (["血常规", "尿常规", "粪常规", "肝功能", "肾功能", "心电图检查", "X线", "超声", "磁共振", "血气分析", "白细胞计数", "血糖", "辅助检查", "脑脊液检查", "骨髓检查"], "实验室及其他辅助检查", "内科学基础（诊断学）", 5),
    (["胸腔穿刺", "腹腔穿刺", "腰椎穿刺", "骨髓穿刺", "导尿", "洗胃", "心包穿刺", "静脉压测定", "穿刺术"], "内科常用的诊断技术", "内科学基础（诊断学）", 6),
    # ===== 外科学 =====
    (["等渗性脱水", "低渗性脱水", "高渗性脱水", "低钾血症", "高钾血症", "水、电解质", "酸碱平衡", "代谢性酸中毒", "代谢性碱中毒", "呼吸性酸中毒", "补钾", "补液", "体液丧失"], "水、电解质代谢和酸碱平衡失调", "外科学（外科总论）", 6),
    (["休克", "微循环障碍", "有效循环血量", "休克指数", "扩容", "弥散性血管内凝血", "休克监测"], "外科休克", "外科学（外科总论）", 6),
    (["外科感染", "疖", "痈", "丹毒", "急性蜂窝织炎", "脓肿", "破伤风", "气性坏疽", "全身性感染", "脓毒症", "急性淋巴管炎"], "外科感染", "外科学（外科总论）", 5),
    (["围手术期", "术前准备", "术后处理", "手术区消毒", "手术切口", "切口分类", "拆线", "术后并发症", "胃肠减压", "吻合口瘘", "肺不张", "术后腹胀", "术后尿潴留"], "围手术期处理", "外科学（外科总论）", 5),
    (["输血", "血液制品", "自身输血", "输血反应", "成分输血", "血浆代用品", "溶血反应"], "输血", "外科学（外科总论）", 6),
    (["多器官功能不全", "多器官衰竭", "急性肾功能衰竭", "急性呼吸窘迫", "MODS", "ARDS", "急性肝衰竭"], "多器官功能不全", "外科学（外科总论）", 6),
    (["外科营养", "肠内营养", "肠外营养", "胃肠外营养", "要素饮食"], "外科营养", "外科学（外科总论）", 6),
    (["创伤", "烧伤", "清创", "止血", "包扎", "搬运", "伤口愈合", "烧伤面积", "烧伤深度", "冷疗", "浅部伤口", "刺伤", "撕裂伤"], "创伤和烧伤", "外科学（外科总论）", 5),
    (["肿瘤", "癌", "良性肿瘤", "恶性肿瘤", "转移", "化疗", "放疗", "TNM", "活检", "癌前病变", "早期胃癌", "分化"], "肿瘤", "外科学（外科总论）", 5),
    (["复苏", "心肺复苏", "胸外心脏按压", "人工呼吸", "心脏骤停", "除颤", "气道开放", "脑复苏", "缺氧耐受"], "复苏", "外科学（外科总论）", 6),
]


def anchor_scores(qtext):
    """返回 {部分: 分数, 章节: 分数}"""
    parts, chaps = defaultdict(float), defaultdict(float)
    for kws, chap_kw, part, w in A:
        hit = sum(w for k in kws if k in qtext)
        if hit:
            chaps[chap_kw] += hit
            if part:
                parts[PART_SHORT.get(part, part)] += hit
    return parts, chaps


# ------------------------------------------------------------ 主流程
def main():
    points = load_points()
    chapters = sorted({(PART_SHORT.get(p, p), c) for p, c, _, _ in points})
    print("复习资料：%d 考点 / %d 章节 / %d 部分" % (len(points), len(chapters), len({p for p, _ in chapters})))

    # 文档 = 考点（标题加权 3 倍）
    docs = []
    for p, c, pt, t in points:
        toks = bigrams(pt) * 3 + bigrams(t) + bigrams(c)
        docs.append((PART_SHORT.get(p, p), c, toks))   # 统一用简称作部分键
    df = Counter()
    for _, _, d in docs:
        for bg in set(d):
            df[bg] += 1
    N = len(docs)
    idf = {bg: math.log(N / (1 + v)) + 1 for bg, v in df.items()}
    vecs = []
    for p, c, d in docs:
        tf = Counter(d)
        v = {bg: (1 + math.log(n)) * idf.get(bg, 1.0) for bg, n in tf.items()}
        vecs.append((p, c, v, math.sqrt(sum(x * x for x in v.values())) or 1.0))

    # 章节规模惩罚基数
    chap_n = Counter(c for _, c, _ in docs)
    part_chaps = defaultdict(set)
    for p, c in chapters:
        part_chaps[p].add(c)

    bank = json.load(open(BANK, encoding="utf-8"))
    dist = Counter()
    low = []
    ALPHA = 0.010

    for q in bank:
        # 匹配文本 = 题干 + 选项 + 答案解析。AI 解析本就依复习资料生成，
        # 措辞与考点高度同源，是比题干更强的分类信号。
        qtext = q["s"] + " " + " ".join(o["t"] for o in q["o"])
        qtext += " " + " ".join(o["t"] for o in q["o"] if o["k"] in q["a"])
        qmatch = qtext + " " + q["exp"]["ai"] + " " + q["exp"]["base"]
        tf = Counter(bigrams(qmatch))
        qv = {bg: (1 + math.log(n)) * idf.get(bg, 1.0) for bg, n in tf.items()}
        qnorm = math.sqrt(sum(x * x for x in qv.values())) or 1.0

        # 每个考点的余弦
        sims = []
        for p, c, v, nrm in vecs:
            s = 0.0
            for bg, w in qv.items():
                if bg in v:
                    s += w * v[bg]
            sims.append((s / (qnorm * nrm), p, c))

        ap, ac = anchor_scores(qtext)

        # ---- 第 1 级：选部分 ----
        part_score = defaultdict(float)
        for sim, p, c in sims:
            if sim > part_score[p]:
                part_score[p] = sim
        for p, sc in ap.items():                       # 锚点（部分级）加权
            part_score[p] += 0.04 * sc
        part = max(part_score, key=part_score.get)

        # ---- 第 2 级：在本部分内选章节 ----
        chap_score = defaultdict(float)
        for sim, p, c in sims:
            if p == part and sim > chap_score[c]:
                chap_score[c] = sim
        for c, sc in ac.items():                       # 锚点（章节级）加权
            for p, cc in chapters:                     # 锚点用短名，需子串匹配全名
                if p == part and c in cc:
                    chap_score[cc] += 0.04 * sc
        for c in list(chap_score):                     # 规模惩罚
            chap_score[c] -= ALPHA * math.log(chap_n.get(c, 1))

        ranked = sorted(chap_score.items(), key=lambda x: -x[1])
        champ, best = ranked[0]
        runner = ranked[1][0] if len(ranked) > 1 else ""

        short = part
        clean = lambda c: re.sub(r"^第.{1,3}章\s*", "", c)
        q["cat1"] = short
        q["cat"] = "%s·%s" % (short, clean(champ))
        q["conf"] = round(best, 4)
        q["alt"] = "%s·%s" % (short, clean(runner)) if runner else ""
        q.pop("_cat_dbg", None)
        dist[q["cat"]] += 1
        if best < 0.15:
            low.append(q)

    json.dump(bank, open(BANK, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("=" * 66)
    print("部分分布：")
    by1 = Counter(q["cat1"] for q in bank)
    for k, v in by1.most_common():
        print("  %4d  %s" % (v, k))
    print("-" * 66)
    print("章节分布（%d 类）：" % len(dist))
    for k, v in dist.most_common():
        print("  %4d  %s" % (v, k))
    print("-" * 66)
    print("低置信度（<0.15）：%d 题" % len(low))
    for q in low[:20]:
        print("  [%s %s题] %s -> %s (%.3f)" % (q["paper"], q["n"], q["s"][:24], q["cat"], q["conf"]))


if __name__ == "__main__":
    main()
