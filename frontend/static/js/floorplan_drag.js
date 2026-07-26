// 평면도 가구 드래그 이동 (화면상 이동만, 저장 없음)
//
// 인라인 SVG 안의 [data-draggable] 가구 <g>를 마우스/터치로 잡아 옮긴다.
// 이동은 <g>에 transform="translate(dx,dy)"로만 적용 → 원본 SVG 좌표는 건드리지 않는다.
// result 화면은 토글·상품추가로 SVG가 교체되므로, 교체 후 window.initFloorplanDrag()로 재초기화한다.
(function () {
  function svgScale(svg) {
    const vb = svg.viewBox && svg.viewBox.baseVal;
    const rect = svg.getBoundingClientRect();
    if (!vb || !rect.width || !rect.height) return { x: 1, y: 1 };
    return { x: vb.width / rect.width, y: vb.height / rect.height };
  }

  function getTranslate(g) {
    return { x: parseFloat(g.getAttribute("data-tx")) || 0,
             y: parseFloat(g.getAttribute("data-ty")) || 0 };
  }
  function setTranslate(g, x, y) {
    g.setAttribute("data-tx", x);
    g.setAttribute("data-ty", y);
    g.setAttribute("transform", `translate(${x} ${y})`);
  }

  // 하나의 SVG에 드래그를 붙인다. 이미 붙어있으면 건너뜀(중복 방지).
  function attach(svg) {
    if (!svg || svg.dataset.dragBound === "1") return;
    svg.dataset.dragBound = "1";

    let active = null, start = null;

    svg.addEventListener("pointerdown", (e) => {
      const g = e.target.closest("[data-draggable]");
      if (!g || !svg.contains(g)) return;
      active = g;
      const scale = svgScale(svg);
      const tr = getTranslate(g);
      start = { px: e.clientX, py: e.clientY, tx: tr.x, ty: tr.y, sx: scale.x, sy: scale.y };
      g.style.cursor = "grabbing";
      g.style.opacity = "0.85";
      if (g.setPointerCapture) g.setPointerCapture(e.pointerId);
      e.preventDefault();
    });

    svg.addEventListener("pointermove", (e) => {
      if (!active || !start) return;
      const dx = (e.clientX - start.px) * start.sx;
      const dy = (e.clientY - start.py) * start.sy;
      setTranslate(active, start.tx + dx, start.ty + dy);
    });

    const end = () => {
      if (active) { active.style.cursor = "grab"; active.style.opacity = "1"; }
      active = null; start = null;
    };
    svg.addEventListener("pointerup", end);
    svg.addEventListener("pointerleave", end);

    svg.querySelectorAll("[data-draggable]").forEach((g) => { g.style.cursor = "grab"; });
  }

  // 페이지의 모든 평면도 SVG에 드래그를 붙인다(재호출 안전).
  function initAll() {
    document.querySelectorAll(".floorplan-svg-box svg").forEach(attach);
  }

  // SVG가 교체된 뒤 다시 부를 수 있게 전역에 노출.
  window.initFloorplanDrag = initAll;

  initAll();
})();
