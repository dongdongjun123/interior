# 다음 작업 정리 — ✅ 둘 다 완료 (2026-07-29)

작성: 2026-07-29

두 기능 모두 구현했다. 아래는 무엇을 어떻게 했는지의 기록으로 남긴다.

| 작업 | 상태 | 결과 |
|---|---|---|
| 1. 우클릭 90° 회전 | ✅ 완료 | `floorplan_transform.js` + `floorplan_rotate.js` 신규 |
| 2. 무드별 색상 | ✅ 완료 | 팔레트 4종(warm/cool/neutral/dark), 무드 12종 매핑 |

**계획서의 경고가 실제로 맞았다.** `setTranslate()`가 `transform`을
통째로 덮어써서, 공용 헬퍼(`FloorplanTransform`)를 만들지 않으면
드래그할 때 회전이 사라졌다. 미리 확인해둔 덕에 바로 처리했다.

계획과 달랐던 점:
- 심볼 색이 4종이 아니라 **5종**이었다(`#bfd6de` 추가 발견).
- 카드·페이지 배경이 하드코딩돼 있어 다크 무드에서 흰 카드가 남았다.
  `page_bg`/`card_bg`를 STYLE에 추가해 해결.

---

## (이하 원래 계획 내용)

---

## 1. 가구 우클릭 90° 회전

**견적 30~45분**

평면도에서 가구를 우클릭하면 90°씩 돌아간다. 화면 표시만 바꾸고
원본 좌표(layout JSON)는 건드리지 않는다 — 드래그와 같은 방식.

### 왜 짧은가

- 드래그가 이미 `transform`을 쓴다(`translate(dx dy)`) → `rotate`를 덧붙이면 된다
- 렌더러도 이미 `rotate(90 cx cy)`를 쓰고 있어 검증된 패턴
  ([model2/rule_based_svg.py](../model2/rule_based_svg.py) `symbol_obj`의 회전 분기)

### 할 일

| # | 파일 | 내용 | 규모 |
|---|---|---|---|
| 1 | `model2/rule_based_svg.py` | `draw_obj`에 `data-cx`/`data-cy` 추가 | 2줄 |
| 2 | `frontend/static/js/floorplan_rotate.js` (신규) | 우클릭 → 90° 누적 | ~40줄 |
| 3 | `frontend/templates/result.html`, `floorplan.html` | 스크립트 include | 2줄 |
| 4 | `result_toggle.js`, `result_products.js` | SVG 교체 후 재초기화 | 2줄 |

### 1) 중심 좌표 노출

`draw_obj` 안에 이미 `obj["x"] / ["y"] / ["w"] / ["h"]`가 있다
(`area_pct` 계산에 쓰는 그 값). 한 줄로 낼 수 있다.

```python
cx = float(obj["x"]) + float(obj["w"]) / 2
cy = float(obj["y"]) + float(obj["h"]) / 2
data_attrs += f' data-cx="{cx:.1f}" data-cy="{cy:.1f}"'
```

### 2) 회전 스크립트

```js
g.addEventListener("contextmenu", (e) => {
  e.preventDefault();                       // 브라우저 기본 메뉴 차단
  const deg = ((+g.dataset.rot || 0) + 90) % 360;
  g.dataset.rot = deg;
  applyTransform(g);
});
```

### ⚠ 유일한 함정 — transform 순서

드래그와 회전이 **같은 `transform` 속성을 공유한다.** 순서를 틀리면
가구가 엉뚱한 곳으로 튄다. `translate`를 먼저, `rotate`를 나중에:

```js
// 올바른 합성
g.setAttribute("transform",
  `translate(${tx} ${ty}) rotate(${deg} ${cx} ${cy})`);
```

`floorplan_drag.js`의 `setTranslate()`도 이 합성 함수를 쓰도록 고쳐야
한다. 지금은 `translate`만 쓰고 있어서, 그대로 두면 드래그할 때 회전이
날아간다. **두 스크립트가 같은 헬퍼를 공유하게 만드는 것이 핵심.**

### 회전 대상 제외

`window`, `door`, `rug`는 제외한다. 벽에 붙어 있어 돌리면 벽을 뚫는다.
드래그도 같은 이유로 이미 제외돼 있다(`floorplan_drag.js` 참고).

### 알려진 한계 (작업 후에도 남음)

회전하면 차지하는 자리가 바뀌는데, 겹침 해소(`resolve_overlaps`)는
렌더 시점에만 돈다. 회전 후 다른 가구와 시각적으로 겹칠 수 있다.
데이터는 안전하다(화면 표시만 바뀜).

### 검증 항목

- [ ] 우클릭 시 브라우저 메뉴가 뜨지 않고 90° 회전
- [ ] 4번 누르면 원위치(0→90→180→270→0)
- [ ] **회전 후 드래그해도 회전이 유지된다** (가장 중요)
- [ ] **드래그 후 회전해도 위치가 유지된다**
- [ ] 토글·상품추가로 SVG 교체 후에도 동작
- [ ] 창문·문·러그는 회전되지 않음
- [ ] 툴팁이 방해받지 않음

---

## 2. 무드별 SVG 색상

**견적 1~1.5시간**

무드(따뜻함/차가움 등)에 맞춰 평면도 색을 바꾼다. 형태·배치는 그대로.

### 재료가 이미 있다

- 무드 슬러그 12종 — [shared/config.py](../shared/config.py)의 `SLUG_MAP`
  ```
  natural_wood  warm_cozy  soft_beige  bright_airy  minimal_white
  modern_grey   monochrome_minimal  dark_moody  luxury_modern
  plant_green   vintage_retro  cute_pastel
  ```
- 세션에 `mood_prompt`, `style_tags` (`backend/app.py`)
- 색이 한곳에 모여 있다 — `model2/rule_based_svg.py`의 `STYLE` 딕셔너리

### 걸림돌 — 심볼에 색이 박혀 있다

Freepik 심볼(`frontend/static/floorplan-symbols/*.svg`)은 fill이
하드코딩돼 있다. **단 4색뿐이라 치환이 간단하다:**

| 원본 색 | 역할 |
|---|---|
| `#8aa6b3` | 테두리(진한 톤) |
| `#b5d1db` | 본체(중간 톤) |
| `#deebf2` | 내부(연한 톤) |
| `#ffffff` | 하이라이트 |

`load_symbols()`에서 읽을 때 정규식으로 치환하면 된다. 시안 만들 때
검증된 방식(`tools/`의 추출 스크립트와 같은 접근).

**주의:** `_SYMBOL_CACHE`가 모듈 전역이라 무드가 바뀌면 캐시를 무효화해야
한다. 무드별로 캐시 키를 두는 게 안전하다.

### 할 일

| # | 내용 | 규모 |
|---|---|---|
| 1 | 팔레트 정의 (대표 4종 또는 12종) | ~40줄 |
| 2 | 무드 슬러그 → 팔레트 매핑 | ~15줄 |
| 3 | `load_symbols()`에 색 치환 + 캐시 키 | ~10줄 |
| 4 | `render_svg`가 무드를 받도록 연결 | ~10줄 |

### 팔레트 방향 (미결정 — 정해야 함)

**대표 4종으로 줄이는 안:**

| 팔레트 | 해당 무드 | 방향 |
|---|---|---|
| warm | `natural_wood` `warm_cozy` `soft_beige` `vintage_retro` | 우드·베이지 |
| cool | `bright_airy` `minimal_white` `modern_grey` | 지금과 유사 |
| neutral | `monochrome_minimal` `luxury_modern` | 무채색 |
| dark | `dark_moody` | 어두운 배경 |

12종 전부 만들면 세밀하지만 손이 더 간다. **4종 권장.**

### 검증 항목

- [ ] 무드별로 색이 실제로 바뀐다(방·격자·가구 심볼 모두)
- [ ] 가구 심볼도 함께 바뀐다 (안 바뀌면 "따뜻한 무드인데 가구는 파랑")
- [ ] 무드를 바꿔 다시 렌더하면 캐시가 남지 않는다
- [ ] 다크 팔레트에서 선·텍스트가 읽힌다
- [ ] Freepik 크레딧이 배경과 대비되어 보인다 (라이선스 의무)
- [ ] 렌더 회귀: 기존 layout 전부 성공

---

## 참고: 검색 기능은 정상이다 (확인 완료)

"상품 추가"의 검색이 의심됐으나 **정상 작동한다.**

- `/search-products?q=원목 의자` → 6개 반환
- UI: 상태 "6개 상품", 카드 6개, "평면도에 추가" 버튼 6개
- 추가 클릭 → 평면도 `use` 10 → 11개 (실제 반영)
- 콘솔 에러 없음

`curl`로 테스트했을 때 0개가 나왔던 것은 Git Bash가 한글을 CP949로
인코딩해 보낸 탓이다(로그의 `%BF%F8%B8%F1`). 브라우저는 UTF-8이라 문제없다.
**앱 버그가 아니므로 고칠 것이 없다.**

---

## 참고: 아직 남은 알려진 이슈

- **`plant` 카테고리 추정만 가능** — 제목에 치수가 없어 실측 0%.
  카테고리(`관엽식물` 350×350)로 대체 중.
- **방 크기 미입력 시 상품 실측 크기가 반영되지 않는다.**
  `width_m`/`depth_m`이 없으면 비율 기준이 없어 표준 크기로 그린다.
  업로드 단계에서 안내를 넣을지 검토 필요.
- **겹침 1건 미해결** — `table` 430×280이 방을 지배하는 layout에서
  `bed`/`chair` 68% 겹침. iterations를 늘려도 안 풀리는 교착.
- **`unknown` 타입은 그리지 않는다** — wall art, desk basket 등.
  의도된 동작이나, "사진에 있는데 안 보인다"는 혼란이 있으면
  도면 밖에 "표시하지 않은 항목" 목록을 넣는 안이 있다.
