// 평면도 가구의 transform을 드래그와 회전이 함께 쓰기 위한 공용 헬퍼.
//
// 두 기능이 같은 transform 속성을 쓰기 때문에, 각자 setAttribute하면
// 나중에 쓴 쪽이 앞의 것을 지운다(드래그하면 회전이 날아가는 식).
// 이동량과 각도를 data-*에 따로 보관하고, 항상 둘을 합쳐서 쓴다.
//
// 순서는 translate 먼저, rotate 나중이다. SVG transform은 왼쪽부터
// 적용되므로 이 순서여야 "제자리에서 회전한 뒤 그만큼 이동"이 된다.
// 뒤집으면 회전축이 이동 전 좌표계에 남아 가구가 튄다.
(function () {
  function state(g) {
    return {
      tx: parseFloat(g.getAttribute("data-tx")) || 0,
      ty: parseFloat(g.getAttribute("data-ty")) || 0,
      rot: parseFloat(g.getAttribute("data-rot")) || 0,
    };
  }

  // 회전축은 렌더러가 넣어준 원본 중심(data-cx/cy)을 쓴다.
  // getBBox()는 회전할수록 값이 바뀌어 누적 오차가 생긴다.
  function center(g) {
    return {
      cx: parseFloat(g.getAttribute("data-cx")) || 0,
      cy: parseFloat(g.getAttribute("data-cy")) || 0,
    };
  }

  function apply(g) {
    const { tx, ty, rot } = state(g);
    const { cx, cy } = center(g);
    const parts = [];
    if (tx || ty) parts.push(`translate(${tx} ${ty})`);
    if (rot) parts.push(`rotate(${rot} ${cx} ${cy})`);
    if (parts.length) {
      g.setAttribute("transform", parts.join(" "));
    } else {
      g.removeAttribute("transform");
    }
  }

  function setTranslate(g, x, y) {
    g.setAttribute("data-tx", x);
    g.setAttribute("data-ty", y);
    apply(g);
  }

  function getTranslate(g) {
    const s = state(g);
    return { x: s.tx, y: s.ty };
  }

  // 각도를 step만큼 더한다(0~359로 정규화). 더한 각도를 돌려준다.
  function rotateBy(g, step) {
    const next = (((state(g).rot + step) % 360) + 360) % 360;
    g.setAttribute("data-rot", next);
    apply(g);
    return next;
  }

  window.FloorplanTransform = {
    apply: apply,
    setTranslate: setTranslate,
    getTranslate: getTranslate,
    rotateBy: rotateBy,
  };
})();
