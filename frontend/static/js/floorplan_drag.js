// 평면도 가구 드래그 이동 (화면상 이동만, 저장 없음)
//
// 인라인 SVG 안의 [data-draggable] 가구 <g>를 마우스/터치로 잡아 옮긴다.
// 이동은 <g>에 transform="translate(dx,dy)"로만 적용 → 원본 SVG 좌표는 건드리지 않는다.
// result 화면은 토글·상품추가로 SVG가 교체되므로, 교체 후 window.initFloorplanDrag()로 재초기화한다.
(function () {
  const styleId = "floorplan-drag-cursor-style";
  if (!document.getElementById(styleId)) {
    const style = document.createElement("style");
    style.id = styleId;
    style.textContent = `
      .floorplan-svg-box svg:not([data-edit-enabled="false"]) [data-draggable],
      .floorplan-svg-box svg:not([data-edit-enabled="false"]) [data-draggable] * {
        cursor: grab;
      }
      .floorplan-svg-box svg [data-rotate-handle],
      .floorplan-svg-box svg [data-rotate-handle] *,
      .floorplan-svg-box svg [data-scale-handle],
      .floorplan-svg-box svg [data-scale-handle] * {
        cursor: pointer;
      }
      .floorplan-svg-box svg.floorplan-dragging,
      .floorplan-svg-box svg.floorplan-dragging * {
        cursor: grabbing !important;
      }
    `;
    document.head.appendChild(style);
  }
  function cancelAllDrags() {
    document
      .querySelectorAll(".floorplan-svg-box svg.floorplan-dragging")
      .forEach((svg) => {
        svg.dispatchEvent(new Event("floorplancancel"));
      });
  }
  window.addEventListener("blur", cancelAllDrags);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) cancelAllDrags();
  });

  function svgScale(svg) {
    const vb = svg.viewBox && svg.viewBox.baseVal;
    const rect = svg.getBoundingClientRect();
    if (!vb || !rect.width || !rect.height) return { x: 1, y: 1 };
    return { x: vb.width / rect.width, y: vb.height / rect.height };
  }

  function pointerPosition(svg, parent, event) {
    if (
      svg.createSVGPoint
      && parent
      && typeof parent.getScreenCTM === "function"
    ) {
      const matrix = parent.getScreenCTM();
      if (matrix) {
        const point = svg.createSVGPoint();
        point.x = event.clientX;
        point.y = event.clientY;
        const local = point.matrixTransform(matrix.inverse());
        return { x: local.x, y: local.y, local: true };
      }
    }
    const scale = svgScale(svg);
    return {
      x: event.clientX,
      y: event.clientY,
      sx: scale.x,
      sy: scale.y,
      local: false,
    };
  }

  function getTranslate(g) {
    return { x: parseFloat(g.getAttribute("data-tx")) || 0,
             y: parseFloat(g.getAttribute("data-ty")) || 0 };
  }
  function getAngle(g) {
    return parseFloat(g.getAttribute("data-angle")) || 0;
  }
  function getScale(g) {
    return parseFloat(g.getAttribute("data-scale")) || 1;
  }
  function applyTransform(g, x, y, angle, scale) {
    g.setAttribute(
      "transform",
      `translate(${x} ${y}) rotate(${angle}) scale(${scale})`
    );
  }
  function setTranslate(g, x, y) {
    g.setAttribute("data-tx", x);
    g.setAttribute("data-ty", y);
    applyTransform(g, x, y, getAngle(g), getScale(g));

    const labelId = g.getAttribute("data-label-id");
    const svg = g.ownerSVGElement;
    const label = labelId && svg
      ? svg.querySelector(`#${labelId}`)
      : null;

    if (label) {
      const originX =
        parseFloat(g.getAttribute("data-origin-x")) || 0;
      const originY =
        parseFloat(g.getAttribute("data-origin-y")) || 0;
      const baseX =
        parseFloat(label.getAttribute("data-base-x")) || 0;
      const baseY =
        parseFloat(label.getAttribute("data-base-y")) || 0;

      label.setAttribute(
        "transform",
        `translate(${baseX + x - originX} ${baseY + y - originY})`
      );
    }
  }
  function rotateFurniture(g, step = 90) {
    if (!g || g.getAttribute("data-rotatable") !== "true") return;
    const tr = getTranslate(g);
    const angle = (getAngle(g) + step + 360) % 360;
    g.setAttribute("data-angle", angle);
    applyTransform(g, tr.x, tr.y, angle, getScale(g));
  }
  function resizeFurniture(g, step) {
    if (!g || g.getAttribute("data-resizable") !== "true") return;
    const tr = getTranslate(g);
    const nextScale = Math.min(
      1.8,
      Math.max(
        0.5,
        Math.round((getScale(g) + step) * 10) / 10
      )
    );
    g.setAttribute("data-scale", nextScale);
    applyTransform(g, tr.x, tr.y, getAngle(g), nextScale);
  }

  // 하나의 SVG에 드래그를 붙인다. 이미 붙어있으면 건너뜀(중복 방지).
  function attach(svg) {
    if (!svg || svg.__floorplanDragBound === true) return;
    // A DOM property disappears when SVG markup is serialized/reloaded,
    // unlike data-drag-bound which was accidentally persisted without its
    // event listeners and prevented result-page reinitialization.
    svg.__floorplanDragBound = true;
    svg.removeAttribute("data-drag-bound");

    let active = null, start = null, activePointerId = null;

    svg.addEventListener("pointerdown", (e) => {
      if (svg.dataset.editEnabled === "false") return;
      const scaleHandle = e.target.closest("[data-scale-handle]");
      if (scaleHandle) {
        const resizable = scaleHandle.closest("[data-resizable]");
        const direction = scaleHandle.getAttribute("data-scale-handle");
        resizeFurniture(resizable, direction === "grow" ? 0.1 : -0.1);
        e.preventDefault();
        e.stopPropagation();
        return;
      }

      const rotateHandle = e.target.closest("[data-rotate-handle]");
      if (rotateHandle) {
        const rotatable = rotateHandle.closest("[data-rotatable]");
        rotateFurniture(rotatable, e.shiftKey ? -90 : 90);
        e.preventDefault();
        e.stopPropagation();
        return;
      }

      const labelHandle =
        e.target.closest("[data-drag-for]");
      let g = e.target.closest("[data-draggable]");

      if (!g && labelHandle) {
        const targetId =
          labelHandle.getAttribute("data-drag-for");
        g = Array.from(
          svg.querySelectorAll("[data-draggable]")
        ).find(
          (candidate) => candidate.id === targetId
        ) || null;
      }

      if (!g || !svg.contains(g)) return;
      active = g;
      activePointerId = e.pointerId;
      const tr = getTranslate(g);
      const pointer = pointerPosition(svg, g.parentNode, e);
      start = {
        px: pointer.x,
        py: pointer.y,
        tx: tr.x,
        ty: tr.y,
        sx: pointer.sx || 1,
        sy: pointer.sy || 1,
        local: pointer.local,
        parent: g.parentNode,
      };
      svg.classList.add("floorplan-dragging");
      g.style.opacity = "0.85";
      if (svg.setPointerCapture) {
        svg.setPointerCapture(e.pointerId);
      }
      e.preventDefault();
    });

    svg.addEventListener("pointermove", (e) => {
      if (!active || !start) return;
      const pointer = pointerPosition(svg, start.parent, e);
      const dx = start.local && pointer.local
        ? pointer.x - start.px
        : (e.clientX - start.px) * start.sx;
      const dy = start.local && pointer.local
        ? pointer.y - start.py
        : (e.clientY - start.py) * start.sy;
      setTranslate(active, start.tx + dx, start.ty + dy);
    });

    const end = () => {
      const pointerId = activePointerId;
      if (active) {
        active.style.opacity = "1";
      }
      active = null;
      start = null;
      activePointerId = null;
      svg.classList.remove("floorplan-dragging");
      if (
        pointerId !== null
        && svg.hasPointerCapture
        && svg.hasPointerCapture(pointerId)
      ) {
        svg.releasePointerCapture(pointerId);
      }
    };
    svg.addEventListener("pointerup", end);
    svg.addEventListener("pointercancel", end);
    svg.addEventListener("lostpointercapture", end);
    svg.addEventListener("pointerleave", end);
    svg.addEventListener("floorplancancel", end);
    svg.addEventListener("dblclick", (e) => {
      if (svg.dataset.editEnabled === "false") return;
      const g = e.target.closest("[data-rotatable]");
      if (!g || !svg.contains(g)) return;
      rotateFurniture(g, e.shiftKey ? -90 : 90);
      e.preventDefault();
    });

    svg.querySelectorAll("[data-drag-for]").forEach((label) => {
      label.style.cursor = "grab";
    });
  }

  // 페이지의 모든 평면도 SVG에 드래그를 붙인다(재호출 안전).
  function initAll() {
    document.querySelectorAll(".floorplan-svg-box svg").forEach(attach);
  }

  // SVG가 교체된 뒤 다시 부를 수 있게 전역에 노출.
  window.initFloorplanDrag = initAll;

  initAll();
})();
