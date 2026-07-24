# 오케스트레이터: 사진 → (Florence 탐지) → (Gemini layout, 근거 주입) → SVG 평면도
#
# 왜 이 구조인가:
#   Florence-2 는 transformers==4.49.0 을 요구해 메인 venv(5.x)와 충돌한다.
#   그래서 한 프로세스로 합치지 않고, Florence 는 별도 환경(.env의 ROOMDET_PYTHON)에서
#   subprocess 로 돌려 detection.json 만 받아온다. 두 환경의 접점은 JSON 파일 하나뿐.
#
# 흐름:
#   1) ROOMDET_PYTHON detect.py <사진> --out <det.json>   (GPU 환경)
#   2) det.json → build_evidence_prompt() 로 근거 텍스트   (개수 강제 + top-down 재판단 룰)
#   3) generate_floorplan_for_web(사진, out, detection_evidence=근거, skip_existing=False) → SVG
#
# 사용:
#   python orchestration/run_floorplan.py <사진경로> [--out-dir 출력폴더]
#   반드시 프로젝트 루트에서 실행 (mood_pipeline / model1 import 때문).
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
from pathlib import Path

# Windows 콘솔(cp949)에서도 한글·em-dash 출력이 깨지지 않도록 stdout을 UTF-8로 고정.
# (근거 텍스트에 '—' 등이 있어 그대로 print 하면 UnicodeEncodeError 가 난다.)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# 프로젝트 루트를 import 경로에 추가 (orchestration/ 하위에서 루트 패키지 접근)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from mood_pipeline.detection_evidence import build_evidence_prompt, load_detection  # noqa: E402

ROOMDET_DIR = ROOT / "room-object-detection"


def run_florence(image_path: Path, det_json: Path) -> dict:
    """ROOMDET_PYTHON 환경에서 detect.py 를 subprocess 로 실행해 detection.json 을 만든다.
    ROOMDET_PYTHON 미설정/실패 시 빈 dict 를 반환(근거 없이 Gemini 만 진행)."""
    roomdet_python = os.getenv("ROOMDET_PYTHON", "").strip()
    if not roomdet_python:
        print("[florence] ROOMDET_PYTHON 미설정 → 탐지 건너뜀(근거 없이 진행)")
        return {}
    if not Path(roomdet_python).exists():
        print(f"[florence] ROOMDET_PYTHON 경로 없음: {roomdet_python} → 탐지 건너뜀")
        return {}

    det_json.parent.mkdir(parents=True, exist_ok=True)
    # detect.py 는 room-object-detection/ 안에서 'module' 패키지를 import 하므로 cwd 를 그쪽으로.
    # 입력/출력은 절대경로로 넘겨 cwd 와 무관하게 한다.
    cmd = [
        roomdet_python, "detect.py",
        str(image_path.resolve()),
        "--out", str(det_json.resolve()),
        "--quiet",  # JSON 본문은 파일로만, 콘솔은 조용히
    ]
    print(f"[florence] 실행: {' '.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd, cwd=str(ROOMDET_DIR),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        print(f"[florence] 실행 실패({exc}) → 근거 없이 진행")
        return {}
    if proc.returncode != 0:
        print(f"[florence] detect.py 오류(exit {proc.returncode}) → 근거 없이 진행")
        if proc.stderr:
            print("  stderr:", proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "")
        return {}

    detection = load_detection(det_json)
    print(f"[florence] 탐지 {len(detection.get('objects', []))}개 → {det_json.name}")
    return detection


def main() -> None:
    parser = argparse.ArgumentParser(description="사진 → Florence 근거 → Gemini layout → SVG")
    parser.add_argument("image", help="입력 방 사진 경로")
    parser.add_argument("--out-dir", default="output/floorplans", help="산출물 폴더")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")  # GEMINI_API_KEY, ROOMDET_PYTHON 등

    image_path = Path(args.image)
    if not image_path.exists():
        raise FileNotFoundError(f"사진 없음: {image_path}")
    out_dir = Path(args.out_dir)

    # 1) Florence 탐지 (별도 환경 subprocess). 실패해도 근거 없이 계속.
    det_json = out_dir / f"{image_path.stem}_detection.json"
    detection = run_florence(image_path, det_json)

    # 2) 탐지 결과 → Gemini 근거 텍스트 (없으면 빈 문자열 → 기존 동작)
    evidence = build_evidence_prompt(detection) if detection else ""
    if evidence:
        print(f"[gemini] Florence 근거 주입 ({len(detection.get('objects', []))}개 가구)")
    else:
        print("[gemini] 근거 없이 layout 추출")

    # 3) 사진 → layout → SVG. 근거를 새로 반영하려면 캐시를 건너뛴다(skip_existing=False).
    from model1.pipeline import generate_floorplan_for_web  # 지연 import(.env 로드 후)
    result = generate_floorplan_for_web(
        image_path, out_dir,
        skip_existing=False,
        detection_evidence=evidence or None,
    )

    print("\n=== 완료 ===")
    print(f"SVG      : {result['svg_path']}")
    print(f"가구 수  : {result['object_count']}")
    print(f"치수(m)  : {result.get('dimensions_m')}")


if __name__ == "__main__":
    main()
