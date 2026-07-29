// 평면도 가구 우클릭 90° 회전 (화면상 표시만, 저장 없음)
//
// 가구 <g>를 우클릭하면 90°씩 돌아간다. 4번 누르면 제자리.
// 이동과 같은 transform을 쓰므로 FloorplanTransform 헬퍼로만 쓴다.
// 창/문/러그는 벽에 붙어 있어 돌리면 벽을 뚫으므로 제외한다
// (드래그도 같은 이유로 [data-draggable]이 없다).
(function () {
  const STEP = 90;

  function toast(text) {
    let el = document.getElementById("floorplanRotateHint");
    if (!el) {
      el = document.createElement("div");
      el.id = "floorplanRotateHint";
      el.style.cssText = [
        "position:fixed",
        "left:50%",
        "bottom:28px",
        "transform:translateX(-50%)",
        "z-index:1090",
        "pointer-events:none",
        "opacity:0",
        "transition:opacity .15s ease",
        "padding:8px 14px",
        "border-radius:999px",
        "background:rgba(23,23,23,.9)",
        "color:#fff",
        "font-size:13px",
      ].join(";");
      document.body.appendChild(el);
    }
    el.textContent = text;
    el.style.opacity = "1";
    clearTimeout(el._t);
    el._t = setTimeout(function () {
      el.style.opacity = "0";
    }, 1100);
  }

  function attach(svg) {
    if (!svg || svg.dataset.rotBound === "1") return;
    svg.dataset.rotBound = "1";

    svg.addEventListener("contextmenu", function (e) {
      // 회전 대상은 드래그 가능한 가구와 같다(벽 고정 요소 제외).
      const g = e.target.closest("[data-draggable]");
      if (!g || !svg.contains(g)) return; // 빈 곳은 기본 메뉴를 살려둔다

      e.preventDefault();

      const T = window.FloorplanTransform;
      if (!T) return; // 헬퍼가 없으면 아무것도 하지 않는다(회전 불가)

      const deg = T.rotateBy(g, STEP);
      const name = g.getAttribute("data-label") || "가구";
      toast(name + " " + deg + "°");
    });
  }

  function initAll() {
    document
      .querySelectorAll(".floorplan-svg-box svg")
      .forEach(attach);
  }

  // SVG가 교체된 뒤(토글·상품추가) 다시 부를 수 있게 노출.
  window.initFloorplanRotate = initAll;

  initAll();
})();
