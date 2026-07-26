// result 화면: 가구 유지/제거를 클릭하면 즉시 서버에 반영하고 수정 평면도를 다시 그린다.
(function () {
  const planImg = document.getElementById("modifiedPlanImg");
  const cards = document.querySelectorAll(".selection-summary-card[data-source-index]");
  if (!cards.length) return;

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
      // 평면도 이미지 교체 (캐시 방지 쿼리 추가)
      if (planImg && data.svg_url) {
        planImg.src = data.svg_url + "?t=" + Date.now();
      }
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
