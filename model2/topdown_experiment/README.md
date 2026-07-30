# Gemini 탑뷰 인테리어 실험

기존 `model1`, 웹 백엔드 및 프런트엔드와 연결되지 않은 독립 실험입니다.
프로젝트 루트 `.env`의 `GEMINI_API_KEY`를 읽기만 합니다.

```powershell
# 프로젝트 루트에서 실행
C:\Users\dh\anaconda3\envs\interior_env\python.exe `
  model2\topdown_experiment\run.py `
  frontend\static\uploads\model2_test.png
```

분석 JSON과 배치 가이드만 만들려면:

```powershell
C:\Users\dh\anaconda3\envs\interior_env\python.exe `
  model2\topdown_experiment\run.py `
  frontend\static\uploads\model2_test.png `
  --analysis-only
```

`--analysis-only`여도 로컬 무료 일러스트인 `topdown_illustrated.png`는 생성됩니다.
생략되는 것은 할당량이 필요한 Gemini 이미지 생성 호출뿐입니다.

실제 3D 면과 직교 카메라로 렌더링한 결과는 `topdown_3d.png`에 저장됩니다.

분석 좌표는 렌더링 전에 자동 보정됩니다.

- 벽에 붙은 가구 스냅
- `left_of`, `right_of`, `above`, `below`, `near` 관계 적용
- 큰 고정 가구 우선 배치
- 침대·책상·수납장 등 물리적으로 겹치면 안 되는 가구 충돌 제거
- 러그와 의자-책상처럼 정상적인 겹침은 허용

자동 이동 내역은 `layout.json`의 `solver_adjustments`에서 확인할 수 있습니다.

이미 생성된 `layout.json`을 다시 사용하면 분석 API 호출을 절약할 수 있습니다.

```powershell
C:\Users\dh\anaconda3\envs\interior_env\python.exe `
  model2\topdown_experiment\run.py `
  frontend\static\uploads\model2_test.png `
  --reuse-layout
```

결과는 `model2/output/topdown_experiment/<입력 파일명>/`에 저장됩니다.
