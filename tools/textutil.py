#!/usr/bin/env python3
"""文本清洗工具：LaTeX 还原 + HTML 实体解码。

供 parse_bank.py 与 parse_extras.py 共用 —— 所有面向用户的文本（题干、选项、
解析、复习资料）都必须走 clean_text()，避免某一类字段漏洗。
"""
import html
import re

# ---------------------------------------------------------------- LaTeX 还原
# 上游 OCR / md 转换把公式留成了 LaTeX（\( K^{+} \)、$Ca^{2+}$、Na\_{2}HPO\_{4}），
# 直接显示就是乱码，这里统一还原成纯文本 / Unicode 上下标。
GREEK = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
         "theta": "θ", "lambda": "λ", "mu": "μ", "nu": "ν", "pi": "π", "rho": "ρ",
         "sigma": "σ", "tau": "τ", "phi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
         "Delta": "Δ", "Sigma": "Σ", "Omega": "Ω"}
SUBMAP = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
SUPMAP = str.maketrans("0123456789+-=()", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def latex_to_text(s):
    # 1) \mathrm{...} / \text{...} 取内容。
    #    内容里可能还嵌一层花括号（如 \mathrm{PaCO\_{2}>6.67kPa(50mmHg)}），
    #    所以要用「允许一层嵌套」的写法，并循环到不再变化。
    nest = re.compile(r"\\(?:mathrm|text|mathbf|mathit)\{((?:[^{}]|\{[^{}]*\})*)\}")
    prev = None
    while prev != s:
        prev = s
        s = nest.sub(r"\1", s)
    # 2) 带圈数字 \textcircled{1}
    def _circ(m):
        n = int(m.group(1))
        return CIRCLED[n - 1] if 1 <= n <= len(CIRCLED) else m.group(1)
    s = re.sub(r"\\textcircled\{(\d+)\}", _circ, s)
    # 3) 温度 $1^{\circ} \mathrm{C}$ -> 1℃（需在通用上标处理之前）
    s = re.sub(r"\^\{\\circ\}\s*C", "℃", s)
    s = re.sub(r"\^\{\\circ\}", "°", s)
    # 4) 希腊字母与常用符号
    for k, v in GREEK.items():
        s = s.replace("\\" + k, v)
    s = s.replace("\\sim", "~").replace("\\times", "×").replace("\\cdot", "·")
    s = s.replace("\\circ", "°").replace("\\%", "%").replace("\\leq", "≤") \
         .replace("\\geq", "≥").replace("\\pm", "±").replace("\\rightarrow", "→")
    # 5) 数学定界符：\( \) $ \[ \]
    s = re.sub(r"\\[()\[\]]", "", s)
    s = s.replace("$", "")
    # 6) 上下标：_{12} / _2 / ^{2+} / ^- / ^9
    def _sub(m):
        v = m.group(1) or m.group(2)
        return v.translate(SUBMAP) if all(c in "0123456789+-=()" for c in v) else v
    def _sup(m):
        v = m.group(1) or m.group(2)
        return v.translate(SUPMAP) if all(c in "0123456789+-=()" for c in v) else v
    s = re.sub(r"_(?:\{([^{}]*)\}|([\w+\-]))", _sub, s)
    s = re.sub(r"\^(?:\{([^{}]*)\}|([\w+\-]))", _sup, s)
    # 7) 残留反斜杠
    s = re.sub(r"\\([A-Za-z]+)", r"\1", s)
    s = s.replace("\\", "")
    # 8) 排版清理
    # 上游把公式拆开时留下了空格：`NaHCO _3`、`cmH _2 O`、`V_1 ~ V_5`。
    # 注意：剔除定界符后常留下连续两个空格，所以必须先归一空格再做拼接，
    # 否则「下标 + 单空格 + 字母」的规则会因为两个空格而匹配不上。
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"\s+([\u2080-\u2089\u2070-\u207f])", r"\1", s)             # 下标/上标前不留空格
    s = re.sub(r"([\u2080-\u2089])\s+([A-Za-z])(?![A-Za-z])", r"\1\2", s)  # cmH₂ O -> cmH₂O
    s = re.sub(r"([\u2080-\u2089])\s*/\s*(?=[A-Za-z])", r"\1/", s)          # NaHCO₃ /H -> NaHCO₃/H
    s = re.sub(r"([\u2080-\u2089])\s+([A-Z][A-Za-z]*[\u2080-\u2089])", r"\1\2", s)  # H₂ CO₃ -> H₂CO₃
    s = re.sub(r"\s*~\s*", "~", s)                                          # V₁ ~ V₅ -> V₁~V₅
    s = re.sub(r"\s+([,;.、，。；：）)])", r"\1", s)
    s = re.sub(r"([（(])\s+", r"\1", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def decode_entities(s):
    """把 &lt; &gt; &amp; 等实体还原成字面字符（源 md 里偶见 <、> 被写成实体）。"""
    return html.unescape(s)


def clean_text(s):
    """统一出口：先解码实体，再还原 LaTeX，最后归一空格。"""
    s = decode_entities(s)
    s = latex_to_text(s)
    return re.sub(r"\s{2,}", " ", s).strip()
