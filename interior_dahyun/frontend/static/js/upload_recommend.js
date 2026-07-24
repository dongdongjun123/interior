// 업로드된 이미지 기반 추천 결과 표시
(function () {
  const btn = document.getElementById("uploadRecommendBtn");
  const resultBox = document.getElementById("uploadRecommendResult");

  if (!btn || !resultBox) return;

  function formatPrice(price) {
    if (!price) return "가격 정보 없음";
    return `${Number(price).toLocaleString()}원`;
  }

  function renderError(message) {
    resultBox.innerHTML = `
      <div class="alert alert-warning">
        ${message}
      </div>
    `;
  }

  function renderRecommendations(data) {
    const detectedItems = data.detected_items || [];
    const recommendations = data.recommendations || {};

    let html = `
      <div class="card border-0 shadow-sm p-3">
        <h6 class="mb-2">업로드 이미지 기반 탐지 결과</h6>
        <p class="text-muted mb-3">
          탐지된 가구: ${detectedItems.join(", ")}
        </p>
    `;

    detectedItems.forEach((itemName) => {
      const rec = recommendations[itemName];
      if (!rec) return;

      html += `
        <div class="mb-4">
          <h6 class="fw-bold">${itemName} 추천 상품</h6>
          <p class="text-muted small">검색어: ${rec.search_query}</p>
          <div class="row g-2">
      `;

      (rec.products || []).forEach((product) => {
        html += `
          <div class="col-md-4">
            <a 
              href="${product.link || '#'}" 
              target="_blank" 
              rel="noopener noreferrer"
              class="text-decoration-none text-dark"
            >
              <div class="border rounded-4 p-2 h-100">
                ${
                  product.image
                    ? `<img src="${product.image}" alt="${product.title}" style="width:100%; height:110px; object-fit:cover; border-radius:12px;">`
                    : `<div class="text-muted small">이미지 없음</div>`
                }
                <p class="small fw-semibold mt-2 mb-1" style="height:40px; overflow:hidden;">
                  ${product.title}
                </p>
                <p class="small mb-1">${formatPrice(product.price)}</p>
                <p class="text-muted small mb-0">${product.shop || ""}</p>
              </div>
            </a>
          </div>
        `;
      });

      html += `
          </div>
        </div>
      `;
    });

    html += `</div>`;

    resultBox.innerHTML = html;
  }

  btn.addEventListener("click", async () => {
    resultBox.innerHTML = `
      <div class="text-muted">
        업로드된 이미지를 분석하고 상품을 추천하는 중...
      </div>
    `;

    try {
      const res = await fetch("/recommend-from-upload");
      const data = await res.json();

      if (!data.ok) {
        renderError(data.error || "추천 결과를 불러오지 못했습니다.");
        return;
      }

      renderRecommendations(data);
    } catch (err) {
      console.error(err);
      renderError("네트워크 오류가 발생했습니다.");
    }
  });
})();