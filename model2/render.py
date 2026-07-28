# 노트북 표시용 시각화: 원본 사진 + (PNG/SVG) 평면도 나란히 보기
from __future__ import annotations

from pathlib import Path

from PIL import Image


def plot_floorplan_figure(
    source: Path,
    floorplan_path: Path,
    analysis_path: Path | None = None,
) -> None:
    # 원본 + 2D 평면도 figure (노트북 표시용)
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for font_name in ("Malgun Gothic", "AppleGothic", "NanumGothic"):  # 한글 폰트 후보 순회
        if font_name in {f.name for f in font_manager.fontManager.ttflist}:  # 설치돼 있으면
            plt.rcParams["font.family"] = font_name  # 그 폰트로 지정(한글 깨짐 방지)
            break

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))  # 가로로 2개 패널 생성
    axes[0].imshow(Image.open(source).convert("RGB"))  # 왼쪽: 원본 사진
    axes[0].set_title("원본 (검색 선택)")
    axes[0].axis("off")  # 축 눈금 숨김

    axes[1].imshow(Image.open(floorplan_path).convert("RGB"))  # 오른쪽: 생성된 평면도
    axes[1].set_title("Gemini 2D 평면도")
    axes[1].axis("off")

    if analysis_path and analysis_path.exists():  # 분석 파일이 있으면
        preview = analysis_path.read_text(encoding="utf-8")[:120].replace("\n", " ")  # 앞 120자 미리보기
        fig.suptitle(f"분석 요약: {preview}...", fontsize=10)  # 전체 제목으로 표시

    fig.tight_layout()  # 여백 자동 정리
    plt.show()  # 화면에 출력


def plot_svg_floorplan_figure(
    source: Path,
    svg_path: Path,
    analysis_path: Path | None = None,
    *,
    max_side: int = 520,
) -> None:
    # 원본 사진 + SVG 평면도 (같은 표시 크기, 노트북 HTML)
    import base64  # 이미지를 data URI로 인라인하기 위한 인코딩
    from io import BytesIO  # 메모리 버퍼

    from IPython.display import HTML, display  # 노트북 HTML 출력

    img = Image.open(source).convert("RGB")  # 원본 사진 로드
    iw, ih = img.size  # 원본 가로·세로 크기
    scale = min(1.0, max_side / max(iw, ih))  # 최대 변이 max_side를 넘지 않도록 축소 비율 계산
    display_w, display_h = int(iw * scale), int(ih * scale)  # 표시용 크기

    buf = BytesIO()  # 메모리 버퍼 생성
    img.save(buf, format="PNG")  # 이미지를 PNG로 버퍼에 저장
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")  # base64 문자열로 인코딩(HTML 인라인용)
    svg = svg_path.read_text(encoding="utf-8")  # SVG 텍스트 로드

    panel_style = (
        f"width:{display_w}px;height:{display_h}px;"
        "border:1px solid #ddd;background:#fff;"
        "box-sizing:border-box;overflow:hidden;"
        "display:flex;align-items:center;justify-content:center;"
    )
    img_style = f"width:{display_w}px;height:{display_h}px;object-fit:contain;display:block;"

    title = ""
    if analysis_path and analysis_path.exists():
        preview = analysis_path.read_text(encoding="utf-8")[:120].replace("\n", " ")
        title = f"<p style='font-size:12px;color:#555;margin:0 0 8px 0'>{preview}...</p>"

    html = f"""
    {title}
    <style>
      .fp-pair svg {{ width:100%; height:100%; display:block; }}
    </style>
    <div style="display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap;">
      <div>
        <div style="font-weight:600; margin-bottom:6px;">원본 (검색 선택)</div>
        <div style="{panel_style}">
          <img src="data:image/png;base64,{b64}" style="{img_style}" alt="original" />
        </div>
      </div>
      <div>
        <div style="font-weight:600; margin-bottom:6px;">SVG 2D 평면도 (무료)</div>
        <div class="fp-pair" style="{panel_style}">{svg}</div>
      </div>
    </div>
    """
    display(HTML(html))


def maybe_plot(source: Path, floorplan_path: Path) -> None:
    # 원본+평면도 시각화 헬퍼 (CLI --plot 옵션에서 호출)
    plot_floorplan_figure(source, floorplan_path)
