// 평면도 가구 드래그 이동 (화면상 이동만, 저장 없음)
//
// 인라인 SVG 안의 [data-draggable] 가구 <g>를 마우스/터치로 잡아 옮긴다.
// 이동은 <g>에 transform="translate(dx,dy)"로만 적용 → 원본 SVG 좌표는 건드리지 않는다.
// (저장·재렌더는 다음 단계. 지금은 새로고침하면 원위치로 돌아간다.)
(function () {
  const box = document.querySelector(".floorplan-svg-box");
  if (!box) return;
  const svg = box.querySelector("svg");
  if (!svg) return;

  // 화면 픽셀 이동량 → SVG 좌표 이동량 변환용 스케일.
  // viewBox 너비 / 실제 렌더 폭 = 1픽셀당 SVG 좌표 이동량.
  function svgScale() {
    const vb = svg.viewBox && svg.viewBox.baseVal;
    const rect = svg.getBoundingClientRect();
    if (!vb || !rect.width || !rect.height) return { x: 1, y: 1 };
    return { x: vb.width / rect.width, y: vb.height / rect.height };
  }

  // <g>의 현재 translate 값을 읽는다(없으면 0,0).
  function getTranslate(g) {
    const t = g.getAttribute("data-tx");
    const u = g.getAttribute("data-ty");
    return { x: parseFloat(t) || 0, y: parseFloat(u) || 0 };
  }

  function setTranslate(g, x, y) {
    g.setAttribute("data-tx", x);
    g.setAttribute("data-ty", y);
    g.setAttribute("transform", `translate(${x} ${y})`);
  }

  let active = null; // 현재 드래그 중인 <g>
  let start = null; // 드래그 시작 시점의 포인터·translate

  function onPointerDown(e) {
    const g = e.target.closest("[data-draggable]");
    if (!g || !box.contains(g)) return;
    active = g;
    const scale = svgScale();
    const tr = getTranslate(g);
    start = {
      px: e.clientX,
      py: e.clientY,
      tx: tr.x,
      ty: tr.y,
      sx: scale.x,
      sy: scale.y,
    };
    g.style.cursor = "grabbing";
    g.style.opacity = "0.85";
    // 드래그 중 다른 요소가 포인터를 가로채지 않게 캡처
    if (g.setPointerCapture) g.setPointerCapture(e.pointerId);
    e.preventDefault();
  }

  function onPointerMove(e) {
    if (!active || !start) return;
    // 화면 이동량(px)을 SVG 좌표 이동량으로 변환해 누적 translate에 더한다.
    const dx = (e.clientX - start.px) * start.sx;
    const dy = (e.clientY - start.py) * start.sy;
    setTranslate(active, start.tx + dx, start.ty + dy);
  }

  function onPointerUp() {
    if (active) {
      active.style.cursor = "grab";
      active.style.opacity = "1";
    }
    active = null;
    start = null;
  }

  // 드래그 가능한 가구에 grab 커서 표시
  svg.querySelectorAll("[data-draggable]").forEach((g) => {
    g.style.cursor = "grab";
  });

  svg.addEventListener("pointerdown", onPointerDown);
  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp);
})();
