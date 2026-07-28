// 평면도 가구 툴팁 — 마우스를 올리면 이름·종류·크기·신뢰도를 보여준다.
//
// 렌더러가 가구 <g>에 심어둔 data-* 를 읽는다
// (data-label / data-type-name / data-area-pct / data-confidence / data-product-*).
// 드래그를 방해하지 않도록: 툴팁 자체는 pointer-events:none 이고,
// 드래그 중(pointerdown~up)에는 표시하지 않는다.
(function () {
  var TIP_ID = "floorplanTooltip";
  var OFFSET = 14; // 커서와 툴팁 사이 여백
  var dragging = false;

  function tipEl() {
    var el = document.getElementById(TIP_ID);
    if (el) return el;

    el = document.createElement("div");
    el.id = TIP_ID;
    el.setAttribute("role", "tooltip");
    el.style.cssText = [
      "position:fixed",
      "z-index:1080",
      "pointer-events:none",
      "opacity:0",
      "transition:opacity .12s ease",
      "max-width:260px",
      "padding:10px 12px",
      "border-radius:10px",
      "background:rgba(23,23,23,.94)",
      "color:#fff",
      "font-size:13px",
      "line-height:1.5",
      "box-shadow:0 6px 24px rgba(0,0,0,.28)",
    ].join(";");
    document.body.appendChild(el);
    return el;
  }

  // 신뢰도를 사람이 읽을 수 있는 말로.
  function confidenceText(value) {
    var n = parseFloat(value);
    if (isNaN(n)) return null;
    var word =
      n >= 0.9 ? "매우 확실" : n >= 0.8 ? "확실" : n >= 0.7 ? "보통" : "불확실";
    return word + " (" + Math.round(n * 100) + "%)";
  }

  function buildHtml(g) {
    var d = g.dataset;
    var name = d.label || d.typeName || "가구";
    var rows = [];

    // 이름이 종류와 다를 때만 종류를 따로 보여준다(중복 표기 방지).
    if (d.typeName && d.typeName !== name) {
      rows.push(["종류", d.typeName]);
    }
    if (d.areaPct) {
      rows.push(["방 대비", d.areaPct + "%"]);
    }
    var conf = confidenceText(d.confidence);
    if (conf) {
      rows.push(["인식", conf]);
    }
    if (d.source === "selected_product") {
      rows.push(["구분", "새로 추가한 상품"]);
    }

    var html =
      '<div style="font-weight:600;margin-bottom:2px">' +
      escapeHtml(name) +
      "</div>";

    rows.forEach(function (r) {
      html +=
        '<div style="display:flex;gap:8px">' +
        '<span style="opacity:.65;min-width:48px">' +
        r[0] +
        "</span><span>" +
        escapeHtml(String(r[1])) +
        "</span></div>";
    });

    if (d.productTitle) {
      html +=
        '<div style="margin-top:6px;padding-top:6px;' +
        'border-top:1px solid rgba(255,255,255,.18);opacity:.85">' +
        escapeHtml(d.productTitle) +
        "</div>";
    }

    if (g.hasAttribute("data-draggable")) {
      html +=
        '<div style="margin-top:6px;opacity:.6;font-size:12px">' +
        "끌어서 옮길 수 있어요</div>";
    }

    return html;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function show(g, x, y) {
    var el = tipEl();
    el.innerHTML = buildHtml(g);
    el.style.opacity = "1";
    place(el, x, y);
  }

  function place(el, x, y) {
    // 화면 밖으로 나가지 않게 뒤집는다.
    var r = el.getBoundingClientRect();
    var left = x + OFFSET;
    var top = y + OFFSET;
    if (left + r.width > window.innerWidth - 8) left = x - r.width - OFFSET;
    if (top + r.height > window.innerHeight - 8) top = y - r.height - OFFSET;
    el.style.left = Math.max(8, left) + "px";
    el.style.top = Math.max(8, top) + "px";
  }

  function hide() {
    var el = document.getElementById(TIP_ID);
    if (el) el.style.opacity = "0";
  }

  function attach(svg) {
    if (!svg || svg.dataset.tipBound === "1") return;
    svg.dataset.tipBound = "1";

    svg.addEventListener("pointermove", function (e) {
      if (dragging) return hide();
      var g = e.target.closest("[data-label]");
      if (!g || !svg.contains(g)) return hide();
      show(g, e.clientX, e.clientY);
    });

    svg.addEventListener("pointerleave", hide);

    // 드래그 중에는 툴팁이 방해되므로 감춘다.
    svg.addEventListener("pointerdown", function (e) {
      if (e.target.closest("[data-draggable]")) {
        dragging = true;
        hide();
      }
    });
  }

  function endDrag() {
    dragging = false;
  }
  window.addEventListener("pointerup", endDrag);
  window.addEventListener("pointercancel", endDrag);

  function initAll() {
    document
      .querySelectorAll(".floorplan-svg-box svg")
      .forEach(attach);
  }

  // SVG가 교체된 뒤(토글·상품추가) 다시 부를 수 있게 노출.
  window.initFloorplanTooltip = initAll;

  initAll();
})();
