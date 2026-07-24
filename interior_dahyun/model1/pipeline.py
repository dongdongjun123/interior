# 고수준 파이프라인 단계(run_*_step)와 웹/배치 진입점
from __future__ import annotations

import json
import os
from pathlib import Path

from google import genai

from .client import _get_client
from .config import _load_env
from .gemini_steps import (
    analyze_interior,
    analyze_layout_detail,
    extract_rule_based_layout,
    generate_floorplan,
    generate_floorplan_svg,
    refine_layout,
)
from .io_utils import (
    _analysis_cache_valid,
    _layout_cache_valid,
    _output_paths,
    _rule_layout_cache_valid,
    _rule_layout_needs_coerce,
    _rule_svg_cache_valid,
    _svg_cache_valid,
)


def run_analysis_step(
    client: genai.Client,
    image_path: Path,
    output_dir: Path,
    *,
    analysis_model: str,
    skip_existing: bool = True,
) -> dict:
    # 1단계: 공간 특징 추출 → txt 저장 (API 1회)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = _output_paths(image_path, output_dir)

    # 캐시가 유효하면 API 호출 없이 기존 분석 재사용
    if (
        skip_existing
        and paths["analysis"].exists()
        and _analysis_cache_valid(paths["analysis"])
    ):
        print(
            f"[{image_path.name}] 분석 캐시 사용 "
            f"→ {paths['analysis'].name}"
        )

        return {
            "source": str(image_path),
            "analysis_file": str(paths["analysis"]),
            "analysis_model": analysis_model,
            "skipped": True,
        }

    print(f"[{image_path.name}] 공간 분석 중...")

    analysis = analyze_interior(
        client,
        image_path,
        model=analysis_model,
    )

    paths["analysis"].write_text(
        analysis,
        encoding="utf-8",
    )

    print(
        f"[{image_path.name}] 분석 저장 "
        f"→ {paths['analysis'].name}"
    )

    return {
        "source": str(image_path),
        "analysis_file": str(paths["analysis"]),
        "analysis_model": analysis_model,
        "skipped": False,
    }


def run_rule_based_layout_step(
    client: genai.Client,
    image_path: Path,
    output_dir: Path,
    *,
    analysis_model: str,
    skip_existing: bool = True,
    refine: bool | None = None,
    room_width: float | None = None,
    room_depth: float | None = None,
) -> dict:
    """
    사진을 분석하여 rule-based renderer용 layout JSON을 생성한다.

    사용자가 방 가로와 세로를 입력했다면,
    Gemini 분석이 끝난 뒤 실제 방 비율을 최종 적용한다.
    """
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths = _output_paths(
        image_path,
        output_dir,
    )

    def same_number(
        value,
        expected: float,
    ) -> bool:
        """저장된 숫자와 새 입력값이 같은지 확인한다."""
        try:
            return abs(float(value) - expected) < 0.000001

        except (TypeError, ValueError):
            return False

    def apply_user_dimensions(
        layout: dict,
    ) -> tuple[bool, bool]:
        """
        사용자 입력 가로·세로를 layout에 적용한다.

        반환:
            dimensions_applied:
                유효한 크기값이 전달되었는지

            layout_changed:
                기존 layout 내용이 실제로 변경되었는지
        """
        if (
            room_width is None
            or room_depth is None
            or room_width <= 0
            or room_depth <= 0
        ):
            return False, False

        width_value = float(room_width)
        depth_value = float(room_depth)

        aspect_ratio = round(
            width_value / depth_value,
            4,
        )

        room_data = layout.setdefault(
            "room",
            {},
        )

        room_shape = (
            room_data.get("shape")
            or "rectangle"
        )

        layout_changed = (
            room_data.get("shape") != room_shape
            or not same_number(
                room_data.get("aspect_ratio"),
                aspect_ratio,
            )
            or not same_number(
                room_data.get("width_m"),
                width_value,
            )
            or not same_number(
                room_data.get("depth_m"),
                depth_value,
            )
        )

        room_data["shape"] = room_shape
        room_data["aspect_ratio"] = aspect_ratio
        room_data["width_m"] = width_value
        room_data["depth_m"] = depth_value

        return True, layout_changed

    # 기존 layout JSON 캐시가 있는 경우
    if (
        skip_existing
        and _rule_layout_cache_valid(
            paths["layout"]
        )
    ):
        layout = json.loads(
            paths["layout"].read_text(
                encoding="utf-8",
            )
        )

        (
            dimensions_applied,
            layout_changed,
        ) = apply_user_dimensions(layout)

        # 새 입력 크기가 기존 캐시와 다르면 JSON 갱신
        if layout_changed:
            paths["layout"].write_text(
                json.dumps(
                    layout,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            applied_ratio = round(
                float(room_width) / float(room_depth),
                4,
            )

            print(
                f"[{image_path.name}] "
                f"사용자 입력 방 크기로 layout 캐시 갱신 "
                f"→ {room_width}m × {room_depth}m, "
                f"비율 {applied_ratio}"
            )

        if _rule_layout_needs_coerce(
            paths["layout"]
        ):
            print(
                f"[{image_path.name}] "
                "⚠ 구 스키마 layout 캐시 — "
                "SVG 렌더 시 자동 변환됩니다. "
                "정확한 배치는 FORCE_LAYOUT=True로 "
                "재추출하세요."
            )

        else:
            print(
                f"[{image_path.name}] "
                f"layout JSON 캐시 사용 "
                f"→ {paths['layout'].name}"
            )

        return {
            "source": str(image_path),
            "layout_file": str(paths["layout"]),
            "analysis_model": analysis_model,
            "renderer": "rule_based_v3",
            "dimensions_applied": dimensions_applied,
            "layout_changed": layout_changed,
            "skipped": True,
        }

    # 자기교정 사용 여부
    if refine is None:
        refine = os.getenv(
            "GEMINI_LAYOUT_REFINE",
            "1",
        ).strip().lower() not in (
            "0",
            "false",
            "no",
            "",
        )

    print(
        f"[{image_path.name}] "
        "Gemini layout 추출 중..."
    )

    # 1차 Gemini 분석
    layout = extract_rule_based_layout(
        client,
        image_path,
        model=analysis_model,
    )

    refined = False

    # 자기교정
    if refine:
        try:
            print(
                f"[{image_path.name}] "
                "자기교정(refine) 중... "
                "(API 1회 추가)"
            )

            corrected = refine_layout(
                client,
                image_path,
                layout,
                model=analysis_model,
            )

            layout = corrected
            refined = True

        except Exception as exc:
            print(
                f"[{image_path.name}] "
                "자기교정 건너뜀 "
                f"(1차 결과 사용): {exc}"
            )

    # Gemini 분석 및 자기교정 이후
    # 사용자가 입력한 방 비율을 최종 적용
    (
        dimensions_applied,
        _,
    ) = apply_user_dimensions(layout)

    if dimensions_applied:
        applied_ratio = round(
            float(room_width) / float(room_depth),
            4,
        )

        print(
            f"[{image_path.name}] "
            "사용자 입력 방 비율 적용 "
            f"→ {room_width}m ÷ {room_depth}m "
            f"= {applied_ratio}"
        )

    layout["schema"] = "rule_based_v3"

    paths["layout"].write_text(
        json.dumps(
            layout,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"[{image_path.name}] "
        f"layout 저장 → {paths['layout'].name} "
        f"({len(layout.get('objects', []))} objects, "
        f"refined={refined}, "
        f"dimensions_applied={dimensions_applied})"
    )

    return {
        "source": str(image_path),
        "layout_file": str(paths["layout"]),
        "analysis_model": analysis_model,
        "object_count": len(
            layout.get("objects", [])
        ),
        "renderer": "rule_based_v3",
        "refined": refined,
        "dimensions_applied": dimensions_applied,
        "layout_changed": True,
        "skipped": False,
    }


def run_rule_based_svg_step(
    image_path: Path,
    output_dir: Path,
    *,
    skip_existing: bool = True,
    title: str | None = None,
) -> dict:
    # 파이썬 규칙 기반 렌더러로 SVG 생성
    # Gemini API 호출은 없음
    import importlib

    import mood_pipeline.rule_based_svg as rbs

    # 최신 렌더러 코드 반영
    importlib.reload(rbs)

    save_svg = rbs.save_svg

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths = _output_paths(
        image_path,
        output_dir,
    )

    if not paths["layout"].exists():
        raise FileNotFoundError(
            f"layout JSON 없음: {paths['layout']} — "
            "run_rule_based_layout_step()을 먼저 실행하세요."
        )

    if (
        skip_existing
        and _rule_svg_cache_valid(
            paths["layout"],
            paths["rule_svg"],
        )
    ):
        print(
            f"[{image_path.name}] "
            f"rule-based SVG 캐시 사용 "
            f"→ {paths['rule_svg'].name}"
        )

        return {
            "source": str(image_path),
            "floorplan_svg": str(
                paths["rule_svg"]
            ),
            "layout_file": str(
                paths["layout"]
            ),
            "format": "svg",
            "renderer": "python_rule_based_v3",
            "skipped": True,
        }

    layout = json.loads(
        paths["layout"].read_text(
            encoding="utf-8",
        )
    )

    svg_title = (
        title
        or f"Floor plan — {image_path.stem}"
    )

    print(
        f"[{image_path.name}] "
        "rule-based SVG 렌더링 중... "
        f"(renderer {rbs.RENDERER_VERSION})"
    )

    save_svg(
        layout,
        paths["rule_svg"],
        title=svg_title,
    )

    print(
        f"[{image_path.name}] "
        f"SVG 저장 → {paths['rule_svg'].name}"
    )

    return {
        "source": str(image_path),
        "floorplan_svg": str(
            paths["rule_svg"]
        ),
        "layout_file": str(
            paths["layout"]
        ),
        "format": "svg",
        "renderer": "python_rule_based_v3",
        "skipped": False,
    }


def run_layout_detail_step(
    client: genai.Client,
    image_path: Path,
    output_dir: Path,
    *,
    analysis_model: str,
    skip_existing: bool = True,
) -> dict:
    # 사진+분석 → 상세 좌표 JSON
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths = _output_paths(
        image_path,
        output_dir,
    )

    if not paths["analysis"].exists():
        raise FileNotFoundError(
            f"분석 파일 없음: {paths['analysis']} — "
            "먼저 run_analysis_step()을 실행하세요."
        )

    analysis_mtime = (
        paths["analysis"].stat().st_mtime
    )

    layout_ok = (
        skip_existing
        and _layout_cache_valid(
            paths["layout"]
        )
        and (
            paths["layout"].stat().st_mtime
            >= analysis_mtime
        )
    )

    if layout_ok:
        print(
            f"[{image_path.name}] "
            f"layout JSON 캐시 사용 "
            f"→ {paths['layout'].name}"
        )

        return {
            "source": str(image_path),
            "layout_file": str(
                paths["layout"]
            ),
            "analysis_file": str(
                paths["analysis"]
            ),
            "analysis_model": analysis_model,
            "skipped": True,
        }

    analysis = paths["analysis"].read_text(
        encoding="utf-8",
    )

    print(
        f"[{image_path.name}] "
        "상세 layout JSON 생성 중..."
    )

    layout = analyze_layout_detail(
        client,
        image_path,
        analysis,
        model=analysis_model,
    )

    paths["layout"].write_text(
        json.dumps(
            layout,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"[{image_path.name}] "
        f"layout 저장 → {paths['layout'].name} "
        f"({len(layout.get('objects', []))} objects)"
    )

    return {
        "source": str(image_path),
        "layout_file": str(paths["layout"]),
        "analysis_file": str(paths["analysis"]),
        "analysis_model": analysis_model,
        "object_count": len(
            layout.get("objects", [])
        ),
        "skipped": False,
    }


def run_floorplan_step(
    client: genai.Client,
    image_path: Path,
    output_dir: Path,
    *,
    image_model: str,
    skip_existing: bool = True,
) -> dict:
    # 저장된 분석 + 원본 → 2D 평면도 이미지
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths = _output_paths(
        image_path,
        output_dir,
    )

    if not paths["analysis"].exists():
        raise FileNotFoundError(
            f"분석 파일 없음: {paths['analysis']} — "
            "먼저 run_analysis_step()을 실행하세요."
        )

    if (
        skip_existing
        and paths["plan"].exists()
    ):
        print(
            f"[{image_path.name}] "
            f"평면도 캐시 사용 "
            f"→ {paths['plan'].name}"
        )

        return {
            "source": str(image_path),
            "floorplan": str(paths["plan"]),
            "analysis_file": str(
                paths["analysis"]
            ),
            "image_model": image_model,
            "skipped": True,
        }

    analysis = paths["analysis"].read_text(
        encoding="utf-8",
    )

    print(
        f"[{image_path.name}] "
        "2D 평면도 생성 중..."
    )

    floorplan = generate_floorplan(
        client,
        image_path,
        analysis,
        model=image_model,
    )

    floorplan.save(
        paths["plan"]
    )

    meta = {
        "source": str(image_path),
        "floorplan": str(paths["plan"]),
        "analysis_file": str(
            paths["analysis"]
        ),
        "image_model": image_model,
    }

    paths["meta"].write_text(
        json.dumps(
            meta,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"[{image_path.name}] "
        f"평면도 저장 → {paths['plan'].name}"
    )

    return meta


def run_svg_floorplan_step(
    client: genai.Client,
    image_path: Path,
    output_dir: Path,
    *,
    analysis_model: str,
    skip_existing: bool = True,
) -> dict:
    # 저장된 분석 → SVG 평면도
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths = _output_paths(
        image_path,
        output_dir,
    )

    if not paths["analysis"].exists():
        raise FileNotFoundError(
            f"분석 파일 없음: {paths['analysis']} — "
            "먼저 run_analysis_step()을 실행하세요."
        )

    if (
        skip_existing
        and _svg_cache_valid(
            paths["layout"],
            paths["plan_svg"],
        )
    ):
        print(
            f"[{image_path.name}] "
            f"SVG 평면도 캐시 사용 "
            f"→ {paths['plan_svg'].name}"
        )

        return {
            "source": str(image_path),
            "floorplan_svg": str(
                paths["plan_svg"]
            ),
            "layout_file": str(
                paths["layout"]
            ),
            "analysis_file": str(
                paths["analysis"]
            ),
            "analysis_model": analysis_model,
            "format": "svg",
            "skipped": True,
        }

    # 상세 좌표 JSON 확보
    run_layout_detail_step(
        client,
        image_path,
        output_dir,
        analysis_model=analysis_model,
        skip_existing=skip_existing,
    )

    layout_json = paths["layout"].read_text(
        encoding="utf-8",
    )

    print(
        f"[{image_path.name}] "
        "SVG 평면도 생성 중..."
    )

    svg = generate_floorplan_svg(
        client,
        layout_json,
        image_path,
        model=analysis_model,
    )

    paths["plan_svg"].write_text(
        svg,
        encoding="utf-8",
    )

    meta = {
        "source": str(image_path),
        "floorplan_svg": str(
            paths["plan_svg"]
        ),
        "layout_file": str(
            paths["layout"]
        ),
        "analysis_file": str(
            paths["analysis"]
        ),
        "analysis_model": analysis_model,
        "format": "svg",
        "skipped": False,
    }

    print(
        f"[{image_path.name}] "
        f"SVG 저장 → {paths['plan_svg'].name}"
    )

    return meta


def convert_image(
    client: genai.Client,
    image_path: Path,
    output_dir: Path,
    *,
    analysis_model: str,
    image_model: str,
    skip_existing: bool = False,
) -> dict:
    # 1단계 분석 + 2단계 평면도
    analysis_meta = run_analysis_step(
        client,
        image_path,
        output_dir,
        analysis_model=analysis_model,
        skip_existing=skip_existing,
    )

    floorplan_meta = run_floorplan_step(
        client,
        image_path,
        output_dir,
        image_model=image_model,
        skip_existing=skip_existing,
    )

    return {
        **floorplan_meta,
        "analysis_model": analysis_model,
        "analysis_skipped": analysis_meta.get(
            "skipped",
            False,
        ),
    }


def generate_floorplan_for_web(
    image_path: str | Path,
    output_dir: str | Path,
    *,
    analysis_model: str | None = None,
    skip_existing: bool = True,
    room_width: float | None = None,
    room_depth: float | None = None,
) -> dict:
    """
    웹용 고수준 헬퍼:
    사진 한 장 → layout JSON → 평면도 SVG.

    사용자가 방 가로와 세로를 입력한 경우,
    가로÷세로 비율을 layout JSON과 SVG에 반영한다.

    이후 가구 유지·제거 기능에서 사용할 수 있도록
    layout 파일 경로와 원본 객체 인덱스도 함께 반환한다.
    """
    from .config import DEFAULT_ANALYSIS_MODEL

    _load_env()

    client = _get_client()

    image_path = Path(
        image_path
    )

    output_dir = Path(
        output_dir
    )

    model = (
        analysis_model
        or os.getenv(
            "GEMINI_ANALYSIS_MODEL",
            DEFAULT_ANALYSIS_MODEL,
        )
    )

    # 1. 사진에서 layout JSON 생성
    layout_meta = run_rule_based_layout_step(
        client,
        image_path,
        output_dir,
        analysis_model=model,
        skip_existing=skip_existing,
        room_width=room_width,
        room_depth=room_depth,
    )

    # 방 크기가 변경되었다면
    # 기존 SVG 캐시를 사용하지 않는다.
    layout_changed = bool(
        layout_meta.get(
            "layout_changed"
        )
    )

    svg_skip_existing = (
        skip_existing
        and not layout_changed
    )

    # 2. layout JSON에서 SVG 생성
    svg_meta = run_rule_based_svg_step(
        image_path,
        output_dir,
        skip_existing=(
            svg_skip_existing
        ),
    )

    paths = _output_paths(
        image_path,
        output_dir,
    )

    svg_markup = (
        paths["rule_svg"]
        .read_text(
            encoding="utf-8"
        )
    )

    layout = json.loads(
        paths["layout"]
        .read_text(
            encoding="utf-8"
        )
    )

    room_data = (
        layout.get("room")
        or {}
    )

    furniture_objects = []

    for source_index, obj in enumerate(
        layout.get(
            "objects",
            [],
        )
    ):
        furniture_objects.append(
            {
                # app.py에서 제거할 원본 객체를
                # 정확하게 찾는 데 사용
                "source_index": (
                    source_index
                ),
                "type": str(
                    obj.get("type")
                    or "unknown"
                ),
                "label": str(
                    obj.get("label")
                    or obj.get("type")
                    or "가구"
                ),
            }
        )

    return {
        "svg_path": (
            svg_meta[
                "floorplan_svg"
            ]
        ),
        "layout_file": str(
            paths["layout"]
        ),
        "svg_markup": (
            svg_markup
        ),
        "aspect_ratio": (
            room_data.get(
                "aspect_ratio"
            )
        ),
        "room_width": (
            room_data.get(
                "width_m"
            )
        ),
        "room_depth": (
            room_data.get(
                "depth_m"
            )
        ),
        "dimensions_applied": (
            layout_meta.get(
                "dimensions_applied",
                False,
            )
        ),
        "object_count": len(
            layout.get(
                "objects",
                [],
            )
        ),
        "objects": (
            furniture_objects
        ),
    }
