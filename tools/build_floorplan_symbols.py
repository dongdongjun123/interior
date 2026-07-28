# -*- coding: utf-8 -*-
"""loft-plan.ai -> 가구별 심볼 SVG (영역 안 path만 추림).

get_svg_image()는 전체 도면 + clipPath 방식이라 파일이 162KB씩 나온다.
대신 get_drawings()로 벡터 원본을 읽어, 지정한 영역 안에 있는 도형만
직접 SVG path로 다시 쓴다. 결과는 수 KB 수준.
"""
import io
import sys
from pathlib import Path

import fitz

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SRC = Path(__file__).with_name("loft_3.ai")
OUT = Path(
    r"C:\Users\jundo\Desktop\7min\interior"
    r"\frontend\static\floorplan-symbols"
)

SYMBOLS = [
    ("bed",         91.0,  29.0, 236.5, 226.5, "퀸 침대"),
    ("nightstand",  35.0,  50.5,  87.7,  96.6, "협탁"),
    ("cabinet",    344.9,  29.0, 400.6, 186.0, "장롱/수납장"),
    ("shelf",      423.0, 297.0, 458.6, 450.8, "선반"),
    ("sofa",        29.5, 442.6, 165.0, 771.0, "L자 코너 소파"),
    ("sofa_3seat",  42.9, 254.0, 181.7, 319.2, "3인 소파(비스듬)"),
    ("rug",         85.7, 343.5, 212.5, 431.2, "직사각 러그"),
    ("armchair",   192.0, 442.6, 290.0, 528.0, "안락의자"),
    ("coffee_table", 165.0, 508.0, 240.0, 620.0, "타원 커피테이블"),
    ("desk",       341.1, 266.0, 401.4, 422.4, "책상"),
    ("chair",      292.2, 306.0, 347.6, 373.2, "의자"),
    ("table",      487.9, 197.9, 690.0, 400.0, "원형 식탁+의자"),
    ("round_rug",  527.1, 606.5, 592.6, 672.0, "원형 러그(큰)"),
    ("plant",      484.1, 474.0, 544.8, 535.9, "화분"),
    ("lamp",       356.5, 186.5, 385.5, 215.5, "조명(원형)"),
    ("stool",      432.0,  48.8, 464.3,  81.1, "스툴/작은 원형"),
]

PAD = 1.0   # 경계에서 살짝 여유


def fmt(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s else "0"


def color(c):
    if c is None:
        return "none"
    r, g, b = (max(0, min(1, x)) for x in c[:3])
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def path_d(items, ox: float, oy: float) -> str:
    """drawing item의 세그먼트를 SVG path로. (ox,oy)만큼 평행이동.

    연속된 선/곡선은 하나의 서브패스로 이어 붙여야 한다. 세그먼트마다
    M을 새로 찍으면 도형이 파편으로 끊겨 채움(fill)도 깨진다.
    직전 끝점과 다음 시작점이 같으면 이어서 쓴다.
    """
    d = []
    cur = None          # 현재 펜 위치

    def close_enough(p, q):
        return p is not None and abs(p[0] - q[0]) < 0.01 and abs(p[1] - q[1]) < 0.01

    for seg in items:
        op = seg[0]
        if op == "l":
            a = (seg[1].x - ox, seg[1].y - oy)
            b = (seg[2].x - ox, seg[2].y - oy)
            if not close_enough(cur, a):
                d.append(f"M{fmt(a[0])} {fmt(a[1])}")
            d.append(f"L{fmt(b[0])} {fmt(b[1])}")
            cur = b
        elif op == "c":
            a = (seg[1].x - ox, seg[1].y - oy)
            c1 = (seg[2].x - ox, seg[2].y - oy)
            c2 = (seg[3].x - ox, seg[3].y - oy)
            b = (seg[4].x - ox, seg[4].y - oy)
            if not close_enough(cur, a):
                d.append(f"M{fmt(a[0])} {fmt(a[1])}")
            d.append(
                f"C{fmt(c1[0])} {fmt(c1[1])} "
                f"{fmt(c2[0])} {fmt(c2[1])} "
                f"{fmt(b[0])} {fmt(b[1])}"
            )
            cur = b
        elif op == "re":
            r = seg[1]
            d.append(
                f"M{fmt(r.x0 - ox)} {fmt(r.y0 - oy)}"
                f"h{fmt(r.width)}v{fmt(r.height)}h{fmt(-r.width)}Z"
            )
            cur = None
        elif op == "qu":
            q = seg[1]
            pts = [(q[i].x - ox, q[i].y - oy) for i in range(4)]
            d.append(f"M{fmt(pts[0][0])} {fmt(pts[0][1])}")
            for p in pts[1:]:
                d.append(f"L{fmt(p[0])} {fmt(p[1])}")
            d.append("Z")
            cur = None
    return "".join(d)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(SRC)
    page = doc[0]
    draws = page.get_drawings()

    made = []
    for name, x0, y0, x1, y1, desc in SYMBOLS:
        region = fitz.Rect(x0 - PAD, y0 - PAD, x1 + PAD, y1 + PAD)
        w, h = x1 - x0, y1 - y0
        parts = []
        for it in draws:
            r = it["rect"]
            if r.width < 0.5 and r.height < 0.5:
                continue
            if r.width > w + 4 * PAD or r.height > h + 4 * PAD:
                continue          # 배경/격자/다른 큰 가구
            # 도형 중심이 영역 안이고 대부분 겹치면 채택
            # (contains()만 쓰면 경계에 살짝 걸친 부품이 다 빠진다)
            cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
            if not (region.x0 <= cx <= region.x1 and region.y0 <= cy <= region.y1):
                continue
            ix = min(r.x1, region.x1) - max(r.x0, region.x0)
            iy = min(r.y1, region.y1) - max(r.y0, region.y0)
            area = max(r.width * r.height, 1e-6)
            if ix <= 0 or iy <= 0 or (ix * iy) / area < 0.8:
                continue
            d = path_d(it["items"], x0, y0)
            if not d:
                continue
            if it.get("fill") is not None and not d.endswith("Z"):
                d += "Z"         # 채움 도형은 닫아야 제대로 칠해진다
            fill = color(it.get("fill"))
            stroke = color(it.get("color"))
            lw = it.get("width") or 0
            attrs = [f'd="{d}"', f'fill="{fill}"']
            if stroke != "none" and lw:
                attrs.append(f'stroke="{stroke}"')
                attrs.append(f'stroke-width="{fmt(lw)}"')
            if it.get("even_odd"):
                attrs.append('fill-rule="evenodd"')
            parts.append("<path " + " ".join(attrs) + "/>")

        if not parts:
            print(f"  ! {name}: 도형 없음")
            continue

        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {fmt(w)} {fmt(h)}">'
            f"<!--{desc} | Designed by Freepik-->"
            + "".join(parts)
            + "</svg>\n"
        )
        (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
        made.append((name, w, h, len(svg), len(parts), desc))

    print(f"심볼 {len(made)}개 -> {OUT}")
    for n, w, h, sz, np_, d in made:
        print(f"  {n:<12} {w:6.1f}x{h:6.1f}  {sz:6d}B  path{np_:3d}  {d}")


if __name__ == "__main__":
    main()
