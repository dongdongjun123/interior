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
    output_dir.mkdir(parents=True, exist_ok=True)  # 출력 폴더 없으면 생성
    paths = _output_paths(image_path, output_dir)  # 이 이미지의 산출물 경로 묶음

    # 캐시가 유효하면 API 호출 없이 기존 분석 재사용
    if skip_existing and paths["analysis"].exists() and _analysis_cache_valid(paths["analysis"]):
        print(f"[{image_path.name}] 분석 캐시 사용 → {paths['analysis'].name}")
        return {
            "source": str(image_path),
            "analysis_file": str(paths["analysis"]),
            "analysis_model": analysis_model,
            "skipped": True,  # 건너뛰었음을 표시
        }

    print(f"[{image_path.name}] 공간 분석 중...")
    analysis = analyze_interior(client, image_path, model=analysis_model)  # Gemini로 분석 실행
    paths["analysis"].write_text(analysis, encoding="utf-8")  # 결과를 txt로 저장
    print(f"[{image_path.name}] 분석 저장 → {paths['analysis'].name}")
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
    detection_evidence: str | None = None,
) -> dict:
    # Gemini 1회: 사진 → rule-based renderer용 layout JSON
    # detection_evidence: Florence 탐지 근거 텍스트(선택). extract 단계로 그대로 전달.
    output_dir.mkdir(parents=True, exist_ok=True)  # 출력 폴더 확보
    paths = _output_paths(image_path, output_dir)  # 산출물 경로 묶음

    if skip_existing and _rule_layout_cache_valid(paths["layout"]):  # 유효한 layout 캐시가 있으면
        if _rule_layout_needs_coerce(paths["layout"]):  # 구 스키마면 변환 안내만
            print(
                f"[{image_path.name}] ⚠ 구 스키마 layout 캐시 — SVG 렌더 시 자동 변환됩니다. "
                "정확한 배치는 FORCE_LAYOUT=True 로 재추출하세요."
            )
        else:  # 최신 스키마면 캐시 사용 안내
            print(f"[{image_path.name}] layout JSON 캐시 사용 → {paths['layout'].name}")
        return {  # API 호출 없이 캐시 정보 반환
            "source": str(image_path),
            "layout_file": str(paths["layout"]),
            "analysis_model": analysis_model,
            "renderer": "rule_based_v3",
            "skipped": True,
        }

    if refine is None:  # 자기교정 여부가 지정 안 됐으면 환경변수로 결정
        refine = os.getenv("GEMINI_LAYOUT_REFINE", "1").strip().lower() not in (  # 0/false/no/빈값이면 끄기
            "0",
            "false",
            "no",
            "",
        )

    print(f"[{image_path.name}] Gemini layout 추출 중...")
    layout = extract_rule_based_layout(  # 1차 layout 추출 (근거 있으면 함께 주입)
        client, image_path, model=analysis_model, detection_evidence=detection_evidence
    )
    refined = False  # 교정 적용 여부 플래그
    if refine:  # 자기교정이 켜져 있으면
        try:
            print(f"[{image_path.name}] 자기교정(refine) 중... (API 1회 추가)")
            corrected = refine_layout(client, image_path, layout, model=analysis_model)  # 교정 호출
            layout = corrected  # 교정 결과로 교체
            refined = True
        except Exception as exc:  # 교정 실패해도 1차 결과로 계속 진행
            print(f"[{image_path.name}] 자기교정 건너뜀(1차 결과 사용): {exc}")

    layout["schema"] = "rule_based_v3"  # 최신 스키마 태그 부여
    paths["layout"].write_text(  # layout을 보기 좋게(indent) JSON으로 저장
        json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[{image_path.name}] layout 저장 → {paths['layout'].name} "
        f"({len(layout.get('objects', []))} objects, refined={refined})"
    )
    return {
        "source": str(image_path),
        "layout_file": str(paths["layout"]),
        "analysis_model": analysis_model,
        "object_count": len(layout.get("objects", [])),
        "renderer": "rule_based_v3",
        "refined": refined,
        "skipped": False,
    }


def run_rule_based_svg_step(
    image_path: Path,
    output_dir: Path,
    *,
    skip_existing: bool = True,
    title: str | None = None,
) -> dict:
    # 파이썬 규칙 기반 렌더러로 SVG 생성 (Gemini API 호출 없음)
    import importlib  # 렌더러 모듈 리로드용

    import mood_pipeline.rule_based_svg as rbs  # 규칙 기반 렌더러

    importlib.reload(rbs)  # 렌더러를 다시 로드해 최신 코드 반영
    save_svg = rbs.save_svg  # SVG 저장 함수 참조

    output_dir.mkdir(parents=True, exist_ok=True)  # 출력 폴더 확보
    paths = _output_paths(image_path, output_dir)  # 산출물 경로 묶음

    if not paths["layout"].exists():  # layout JSON이 없으면 렌더 불가
        raise FileNotFoundError(
            f"layout JSON 없음: {paths['layout']} — run_rule_based_layout_step() 먼저 실행"
        )

    if skip_existing and _rule_svg_cache_valid(paths["layout"], paths["rule_svg"]):  # 유효한 SVG 캐시가 있으면
        print(f"[{image_path.name}] rule-based SVG 캐시 사용 → {paths['rule_svg'].name}")
        return {  # 렌더링 없이 캐시 정보 반환
            "source": str(image_path),
            "floorplan_svg": str(paths["rule_svg"]),
            "layout_file": str(paths["layout"]),
            "format": "svg",
            "renderer": "python_rule_based_v3",
            "skipped": True,
        }

    layout = json.loads(paths["layout"].read_text(encoding="utf-8"))  # 저장된 layout 읽어오기
    svg_title = title or f"Floor plan — {image_path.stem}"  # SVG 제목(지정 없으면 파일명 기반)
    print(f"[{image_path.name}] rule-based SVG 렌더링 중... (renderer {rbs.RENDERER_VERSION})")
    save_svg(layout, paths["rule_svg"], title=svg_title)  # layout을 SVG로 렌더링해 저장
    print(f"[{image_path.name}] SVG 저장 → {paths['rule_svg'].name}")
    return {
        "source": str(image_path),
        "floorplan_svg": str(paths["rule_svg"]),
        "layout_file": str(paths["layout"]),
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
    # 1.5단계: 사진+분석 → 상세 좌표 JSON (SVG용, API 1회)
    output_dir.mkdir(parents=True, exist_ok=True)  # 출력 폴더 확보
    paths = _output_paths(image_path, output_dir)  # 산출물 경로 묶음

    if not paths["analysis"].exists():  # 선행 분석 파일이 없으면 진행 불가
        raise FileNotFoundError(
            f"분석 파일 없음: {paths['analysis']} — 먼저 run_analysis_step() 실행"
        )

    analysis_mtime = paths["analysis"].stat().st_mtime  # 분석 파일 수정 시각
    layout_ok = (  # layout 캐시를 재사용할 수 있는 조건
        skip_existing
        and _layout_cache_valid(paths["layout"])  # 유효한 스키마이고
        and paths["layout"].stat().st_mtime >= analysis_mtime  # 분석보다 최신일 때
    )
    if layout_ok:  # 조건 충족 시 캐시 사용
        print(f"[{image_path.name}] layout JSON 캐시 사용 → {paths['layout'].name}")
        return {
            "source": str(image_path),
            "layout_file": str(paths["layout"]),
            "analysis_file": str(paths["analysis"]),
            "analysis_model": analysis_model,
            "skipped": True,
        }

    analysis = paths["analysis"].read_text(encoding="utf-8")  # 저장된 분석 텍스트 로드
    print(f"[{image_path.name}] 상세 layout JSON 생성 중...")
    layout = analyze_layout_detail(client, image_path, analysis, model=analysis_model)  # 좌표 JSON 생성
    paths["layout"].write_text(  # 결과를 JSON으로 저장
        json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[{image_path.name}] layout 저장 → {paths['layout'].name} ({len(layout.get('objects', []))} objects)")
    return {
        "source": str(image_path),
        "layout_file": str(paths["layout"]),
        "analysis_file": str(paths["analysis"]),
        "analysis_model": analysis_model,
        "object_count": len(layout.get("objects", [])),
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
    # 2단계: 저장된 분석 + 원본 → 2D 평면도 이미지 (API 1회)
    output_dir.mkdir(parents=True, exist_ok=True)  # 출력 폴더 확보
    paths = _output_paths(image_path, output_dir)  # 산출물 경로 묶음

    if not paths["analysis"].exists():  # 선행 분석 파일이 없으면 진행 불가
        raise FileNotFoundError(
            f"분석 파일 없음: {paths['analysis']} — 먼저 run_analysis_step() 실행"
        )

    if skip_existing and paths["plan"].exists():  # 이미 평면도가 있으면 재사용
        print(f"[{image_path.name}] 평면도 캐시 사용 → {paths['plan'].name}")
        return {
            "source": str(image_path),
            "floorplan": str(paths["plan"]),
            "analysis_file": str(paths["analysis"]),
            "image_model": image_model,
            "skipped": True,
        }

    analysis = paths["analysis"].read_text(encoding="utf-8")  # 저장된 분석 텍스트 로드
    print(f"[{image_path.name}] 2D 평면도 생성 중...")
    floorplan = generate_floorplan(client, image_path, analysis, model=image_model)  # 평면도 이미지 생성
    floorplan.save(paths["plan"])  # PNG로 저장

    meta = {  # 처리 결과 메타데이터 구성
        "source": str(image_path),
        "floorplan": str(paths["plan"]),
        "analysis_file": str(paths["analysis"]),
        "image_model": image_model,
    }
    paths["meta"].write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")  # 메타 저장
    print(f"[{image_path.name}] 평면도 저장 → {paths['plan'].name}")
    return meta  # 메타데이터 반환


def run_svg_floorplan_step(
    client: genai.Client,
    image_path: Path,
    output_dir: Path,
    *,
    analysis_model: str,
    skip_existing: bool = True,
) -> dict:
    # 2단계(무료): 저장된 분석 → SVG 평면도 (텍스트 API 1회)
    output_dir.mkdir(parents=True, exist_ok=True)  # 출력 폴더 확보
    paths = _output_paths(image_path, output_dir)  # 산출물 경로 묶음

    if not paths["analysis"].exists():  # 선행 분석 파일이 없으면 진행 불가
        raise FileNotFoundError(
            f"분석 파일 없음: {paths['analysis']} — 먼저 run_analysis_step() 실행"
        )

    if skip_existing and _svg_cache_valid(paths["layout"], paths["plan_svg"]):  # 유효한 SVG 캐시가 있으면
        print(f"[{image_path.name}] SVG 평면도 캐시 사용 → {paths['plan_svg'].name}")
        return {  # 생성 없이 캐시 정보 반환
            "source": str(image_path),
            "floorplan_svg": str(paths["plan_svg"]),
            "layout_file": str(paths["layout"]),
            "analysis_file": str(paths["analysis"]),
            "analysis_model": analysis_model,
            "format": "svg",
            "skipped": True,
        }

    run_layout_detail_step(  # 먼저 상세 좌표 JSON을 확보(없으면 생성)
        client,
        image_path,
        output_dir,
        analysis_model=analysis_model,
        skip_existing=skip_existing,
    )
    layout_json = paths["layout"].read_text(encoding="utf-8")  # 좌표 JSON 로드
    print(f"[{image_path.name}] SVG 평면도 생성 중...")
    svg = generate_floorplan_svg(client, layout_json, image_path, model=analysis_model)  # SVG 생성
    paths["plan_svg"].write_text(svg, encoding="utf-8")  # SVG 파일로 저장

    meta = {  # 처리 결과 메타데이터 구성
        "source": str(image_path),
        "floorplan_svg": str(paths["plan_svg"]),
        "layout_file": str(paths["layout"]),
        "analysis_file": str(paths["analysis"]),
        "analysis_model": analysis_model,
        "format": "svg",
        "skipped": False,
    }
    print(f"[{image_path.name}] SVG 저장 → {paths['plan_svg'].name}")
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
    # 1단계 분석 + 2단계 평면도 (한 번에)
    analysis_meta = run_analysis_step(  # 1단계: 공간 분석
        client,
        image_path,
        output_dir,
        analysis_model=analysis_model,
        skip_existing=skip_existing,
    )
    floorplan_meta = run_floorplan_step(  # 2단계: 평면도 이미지 생성
        client,
        image_path,
        output_dir,
        image_model=image_model,
        skip_existing=skip_existing,
    )
    return {  # 두 단계 결과를 합쳐 반환
        **floorplan_meta,
        "analysis_model": analysis_model,
        "analysis_skipped": analysis_meta.get("skipped", False),  # 분석이 캐시로 스킵됐는지
    }


def generate_floorplan_for_web(
    image_path: str | Path,
    output_dir: str | Path,
    *,
    analysis_model: str | None = None,
    skip_existing: bool = True,
    detection_evidence: str | None = None,
) -> dict:
    """웹(backend)용 고수준 헬퍼: 사진 한 장 → 평면도 SVG + 방 정보.

    내부에서 layout 추출(Gemini 1회) → 규칙 기반 SVG 렌더(무료)를 수행하고,
    backend가 바로 화면에 쓸 수 있도록 SVG 마크업과 방 정보를 함께 반환한다.

    detection_evidence: Florence 탐지 근거 텍스트(선택). 있으면 layout 추출 시
        개수·클래스를 사실로 강제하고 top-down 재판단 룰을 지시한다.
        (근거를 새로 반영하려면 skip_existing=False 로 호출해 캐시를 건너뛸 것.)

    반환: {
        "svg_path": SVG 파일 경로(str),
        "svg_markup": <svg>...</svg> 문자열(HTML 삽입용),
        "aspect_ratio": 가로÷세로 비율(float 또는 None),
        "dimensions_m": 실측 치수(m) 또는 None,
        "object_count": 배치된 가구 수(int),
    }
    """
    from .config import DEFAULT_ANALYSIS_MODEL  # 지연 import로 최신 .env 반영값 사용

    _load_env()  # .env 로드(API 키)
    client = _get_client()  # Gemini 클라이언트
    image_path = Path(image_path)
    output_dir = Path(output_dir)
    model = analysis_model or os.getenv("GEMINI_ANALYSIS_MODEL", DEFAULT_ANALYSIS_MODEL)  # 분석 모델 결정

    # 1) 사진 → layout JSON (Gemini 호출, 캐시 있으면 재사용, 근거 있으면 주입)
    run_rule_based_layout_step(
        client, image_path, output_dir,
        analysis_model=model, skip_existing=skip_existing,
        detection_evidence=detection_evidence,
    )
    # 2) layout JSON → SVG 파일 (Gemini 호출 없음)
    svg_meta = run_rule_based_svg_step(
        image_path, output_dir, skip_existing=skip_existing,
    )

    paths = _output_paths(image_path, output_dir)  # 산출물 경로 묶음
    svg_markup = paths["rule_svg"].read_text(encoding="utf-8")  # 생성된 SVG 원문
    layout = json.loads(paths["layout"].read_text(encoding="utf-8"))  # 방 정보 추출용

    room = layout.get("room") or {}
    return {
        "svg_path": svg_meta["floorplan_svg"],
        "svg_markup": svg_markup,
        "aspect_ratio": room.get("aspect_ratio"),
        "dimensions_m": room.get("dimensions_m"),  # 실측 치수(m) — 없으면 None
        "object_count": len(layout.get("objects", [])),
    }
