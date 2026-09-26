#!/usr/bin/env python3
"""从扫描版真题 PDF 中裁切题目插图，产出 data/figures.json。

背景：这批 PDF 没有文本层、也没有独立矢量图，每页就是一整张扫描位图，
因此「提取原图」实际是「在扫描页上定位图区并按高分辨率重新渲染裁切」。
仅 2019 年真题第 4 页的 44 题恰好带一个独立内嵌图片对象，可直接取原图。

各卷扫描分辨率不一致（2020 年真题约为 2 倍 A4，直接按固定 dpi 渲染单页会超 100MB），
故统一按长边目标像素反算 dpi。

裁切清单：figures_manifest.json（项目根目录，人工核定）
输出：
  figures/<id>.png    灰度、自动对比度后的插图
  data/figures.json   [{id, q:{paper,n,type}, cap, w, h, d:"data:image/png;base64,..."}]

用法：
  python3 tools/extract_figures.py [--pdf-dir DIR] [--check]

依赖（不在标准库内，需有 numpy / Pillow / PyMuPDF 的环境）：
  pip install numpy pillow pymupdf
"""
import os
import io
import re
import sys
import json
import base64
import argparse
import glob

try:
    import numpy as np
    import pymupdf as fitz
    from PIL import Image, ImageOps
except ImportError as e:
    sys.exit("本脚本需要 numpy / Pillow / PyMuPDF：pip install numpy pillow pymupdf\n（缺失：%s）" % e)
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
FIGS = os.path.join(BASE, "figures")
MANIFEST = os.path.join(BASE, "figures_manifest.json")   # 人工核定，属源文件（勿放进 data/，那是生成物目录）
DEFAULT_PDF_DIR = os.path.expanduser("~/Downloads/成考资料/医学综合")

SCAN_TARGET_LONG = 2400      # 定位用渲染：长边目标像素
OUT_DPI = 400                # 输出槽素：正式裁切渲染 dpi
FIG_MAX_W = 1500             # 输出图片最大宽度（再宽对屏幕显示无意义，只增体积）


def paper_name(path):
    return os.path.basename(path).replace("与答案含解析（扫描）.pdf", "") \
             .replace("全国统一考试专升本医学综合", "")


def find_pdf(pdf_dir, paper):
    for sub in ("真题", "模拟题"):
        for p in glob.glob(os.path.join(pdf_dir, sub, "*.pdf")):
            if paper_name(p) == paper:
                return p
    return None


def render(page, target_long=SCAN_TARGET_LONG):
    r = page.rect
    dpi = int(round(max(60.0, min(240.0, 72.0 * target_long / max(r.width, r.height)))))
    px = page.get_pixmap(dpi=dpi)
    a = np.frombuffer(px.samples, dtype=np.uint8).reshape(px.height, px.width, px.n)
    a = np.repeat(a, 3, axis=2) if px.n == 1 else a[:, :, :3]
    return np.ascontiguousarray(a), dpi


def _runs(mask, max_gap=18):
    idx = np.nonzero(mask)[0]
    if len(idx) == 0:
        return []
    segs, s, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev <= max_gap:
            prev = i
        else:
            segs.append((s, prev + 1)); s = prev = i
    segs.append((s, prev + 1))
    return sorted(segs, key=lambda x: x[1] - x[0], reverse=True)


def tight_bbox(img, y0, y1, thresh=175, xlo=None, xhi=None):
    """在给定纵向区间（必要时限定横向范围）内求紧致包围盒；
    去噪方式：只取最长连续墨迹块，避免扫描噪点把边界带偏"""
    y0, y1 = int(max(0, y0)), int(y1)
    band = img[y0:y1]
    if band.size == 0:
        return None
    h = band.shape[0]
    ink = band < thresh
    cr = _runs(ink.sum(axis=0) > max(3, int(h * 0.010)))
    if not cr:
        return None
    x0, x1 = cr[0]
    if xlo is not None:
        x0 = max(x0, int(xlo))
    if xhi is not None:
        x1 = min(x1, int(xhi))
    if x1 - x0 < 20:
        return None
    rr = _runs(ink[:, x0:x1].sum(axis=1) > max(3, int((x1 - x0) * 0.010)))
    if not rr:
        return None
    return x0, y0 + rr[0][0], x1, y0 + rr[0][1]


WEBP_Q = 78                 # WebP 质量：扫描线稿在 78 下肉眼看不出损失，体积约为 PNG 的一半


def to_gray_webp(img_arr, out_path, quality=WEBP_Q):
    """灰度化 + 自动对比度 + 限宽，输出 WebP（内联 base64 时体积比 PNG 小得多）"""
    im = Image.fromarray(img_arr).convert("L")
    im = ImageOps.autocontrast(im, cutoff=1)
    if im.width > FIG_MAX_W:
        im = im.resize((FIG_MAX_W, max(1, int(im.height * FIG_MAX_W / im.width))), Image.LANCZOS)
    im.save(out_path, "WEBP", quality=quality, method=6)
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", default=DEFAULT_PDF_DIR)
    ap.add_argument("--check", action="store_true", help="只校验清单，不产出")
    args = ap.parse_args()

    if not os.path.exists(MANIFEST):
        sys.exit("缺少裁切清单 %s" % MANIFEST)
    manifest = json.load(open(MANIFEST, encoding="utf-8"))
    os.makedirs(FIGS, exist_ok=True)

    out, problems = [], []
    for e in manifest:
        fid, paper = e["id"], e["paper"]
        pdf = find_pdf(args.pdf_dir, paper)
        if not pdf:
            problems.append("%s: 找不到 PDF（%s）" % (fid, paper))
            continue
        doc = fitz.open(pdf)
        pg = doc[e["page"] - 1]
        try:
            if e["mode"] == "embed":
                pix = fitz.Pixmap(doc, e["xref"])
                if pix.n - pix.alpha >= 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
                drop = e.get("drop_top", 0.0)
                if drop:
                    a = a[int(a.shape[0] * drop):]
                if e.get("scale", 1) != 1:
                    im = Image.fromarray(a).convert("L")
                    im = im.resize((im.width * e["scale"], im.height * e["scale"]), Image.LANCZOS)
                    im = ImageOps.autocontrast(im, cutoff=1)
                    im.save(os.path.join(FIGS, fid + ".webp"), "WEBP", quality=WEBP_Q, method=6)
                    img_arr, size = np.array(im.convert("RGB")), im.size
                else:
                    im = to_gray_webp(a, os.path.join(FIGS, fid + ".webp"))
                    size = im.size
                note = "内嵌图片对象 xref=%d" % e["xref"]
            elif e["mode"] == "rect":
                # 显式区域：适合半色调照片（像素偏亮，墨迹自动探测会失败）
                r = e["rect_pt"]
                rect = fitz.Rect(r[0], r[1], r[2], r[3]) & pg.rect
                pm = pg.get_pixmap(dpi=OUT_DPI, clip=rect)
                arr = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width, pm.n)[:, :, :3]
                im = to_gray_webp(arr, os.path.join(FIGS, fid + ".webp"))
                size = im.size
                note = "显式区域 rect=%s" % [round(v, 1) for v in rect]
            else:
                scan, dpi = render(pg)
                k = dpi / 72.0
                y0, y1 = e["y_pt"][0] * k, e["y_pt"][1] * k
                xr = e.get("x_pt")
                bb = tight_bbox(scan, y0, y1,
                                xlo=(xr[0] * k) if xr else None,
                                xhi=(xr[1] * k) if xr else None)
                if bb is None:
                    problems.append("%s: 区间 [%.0f,%.0f] 内未找到墨迹" % (fid, y0, y1))
                    continue
                x0, ty0, x1, ty1 = bb
                pad = e.get("pad", 6)
                rect = fitz.Rect((x0 - pad) / k, (ty0 - pad) / k,
                                 (x1 + pad) / k, (ty1 + pad) / k) & pg.rect
                pm = pg.get_pixmap(dpi=OUT_DPI, clip=rect)
                arr = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width, pm.n)[:, :, :3]
                im = to_gray_webp(arr, os.path.join(FIGS, fid + ".webp"))
                size = im.size
                note = "页面裁切 rect=%s" % [round(v, 1) for v in rect]
        finally:
            doc.close()

        path = os.path.join(FIGS, fid + ".webp")
        with open(path, "rb") as f:
            b64 = __import__("base64").b64encode(f.read()).decode("ascii")
        out.append({"id": fid, "q": e.get("q"), "cap": e.get("cap", ""),
                    "w": size[0], "h": size[1], "src": note,
                    "kb": round(os.path.getsize(path) / 1024.0),
                    "d": "data:image/webp;base64," + b64})
        print("%-14s %4dx%-4d %6.1f KB  %s" % (fid, size[0], size[1],
                                               os.path.getsize(path) / 1024.0, note))

    if problems:
        print("\n问题：")
        for p in problems:
            print("  " + p)
    if not args.check:
        json.dump(out, open(os.path.join(DATA, "figures.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        tot = sum(o["kb"] for o in out)
        print("\n共 %d 张，合计 %.2f MB（base64 内联后约 %.2f MB）"
              % (len(out), tot / 1024.0, tot * 1.34 / 1024.0))
        print("已写出 data/figures.json 与 figures/")


if __name__ == "__main__":
    main()
