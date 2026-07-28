// result 화면: 가구 유지/제거를 클릭하면 즉시 서버에 반영하고 수정 평면도를 다시 그린다.
(function () {
  const planBox = document.getElementById("modifiedPlanBox");
  const cards = document.querySelectorAll(".selection-summary-card[data-source-index]");
  if (!cards.length) return;

  // AJAX로 받은 새 SVG markup으로 평면도를 교체하고 드래그를 다시 붙인다.
  function replacePlan(markup) {
    if (planBox && markup) {
      planBox.innerHTML = markup;
      if (window.initFloorplanDrag) window.initFloorplanDrag();
      if (window.initFloorplanTooltip) window.initFloorplanTooltip();
    }
  }

  async function toggle(card, decision) {
    const si = card.getAttribute("data-source-index");
    if (si === null || si === "" || si === "None") return;

    const group = card.querySelector(".furniture-toggle");
    if (group) group.style.opacity = "0.5"; // 처리 중 표시

    try {
      const res = await fetch("/toggle-furniture", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ source_index: parseInt(si, 10), decision }),
      });
      const data = await res.json();
      if (!data.ok) {
        console.error("toggle 실패:", data.error);
        return;
      }
      // 버튼 상태 갱신
      const keepBtn = card.querySelector('[data-decision="keep"]');
      const removeBtn = card.querySelector('[data-decision="remove"]');
      const removed = data.decision === "remove";
      keepBtn.className = "btn " + (removed ? "btn-outline-secondary" : "btn-dark");
      removeBtn.className = "btn " + (removed ? "btn-danger" : "btn-outline-danger");
      // 평면도 SVG 교체 + 드래그 재바인딩
      replacePlan(data.svg_markup);
    } catch (err) {
      console.error("toggle 네트워크 오류:", err);
    } finally {
      if (group) group.style.opacity = "1";
    }
  }

  cards.forEach((card) => {
    card.querySelectorAll(".furniture-toggle [data-decision]").forEach((btn) => {
      btn.addEventListener("click", () => toggle(card, btn.getAttribute("data-decision")));
    });
  });
})();
