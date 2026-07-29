// result 화면: 네이버 상품을 검색해 평면도에 새 가구로 추가한다.
(function () {
  const typeSel = document.getElementById("productType");
  const queryInput = document.getElementById("productQuery");
  const searchBtn = document.getElementById("productSearchBtn");
  const status = document.getElementById("productSearchStatus");
  const results = document.getElementById("productResults");
  const planBox = document.getElementById("modifiedPlanBox");
  if (!searchBtn || !results) return;

  const won = (n) => (n ? Number(n).toLocaleString() + "원" : "가격 정보 없음");

  function card(product) {
    const col = document.createElement("div");
    col.className = "col-6 col-md-4 col-lg-3";
    col.innerHTML = `
      <div class="border rounded-4 p-2 h-100 d-flex flex-column" style="cursor:pointer;">
        <div style="aspect-ratio:1/1; overflow:hidden; border-radius:8px; background:#f0ece4;">
          ${product.image
            ? `<img src="${product.image}" alt="" style="width:100%;height:100%;object-fit:cover;">`
            : `<div class="d-flex align-items-center justify-content-center h-100 text-muted small">이미지 없음</div>`}
        </div>
        <p class="small fw-semibold mt-2 mb-1" style="height:38px;overflow:hidden;">${product.title}</p>
        <p class="small mb-1">${won(product.price)}</p>
        <p class="text-muted small mb-2">${product.shop || ""}</p>
        <button type="button" class="btn btn-sm btn-outline-dark mt-auto add-btn">평면도에 추가</button>
      </div>`;
    const btn = col.querySelector(".add-btn");
    btn.addEventListener("click", () => addProduct(product, btn));
    return col;
  }

  async function search() {
    const q = (queryInput.value || "").trim();
    if (!q) { status.textContent = "검색어를 입력해 주세요."; return; }
    status.textContent = "검색 중…";
    results.innerHTML = "";
    try {
      const res = await fetch("/search-products?q=" + encodeURIComponent(q), {
        credentials: "same-origin",
      });
      const data = await res.json();
      if (!data.ok) { status.textContent = data.error || "검색 실패"; return; }
      if (!data.products.length) { status.textContent = "검색 결과가 없습니다."; return; }
      status.textContent = `${data.products.length}개 상품`;
      data.products.forEach((p) => results.appendChild(card(p)));
    } catch (err) {
      console.error(err);
      status.textContent = "네트워크 오류가 발생했습니다.";
    }
  }

  async function addProduct(product, btn) {
    btn.disabled = true;
    btn.textContent = "추가 중…";
    try {
      const res = await fetch("/add-product", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          type: typeSel.value,
          title: product.title,
          link: product.link,
          image: product.image,
          // 제목에 치수가 없을 때 서버가 카테고리로 크기를 추정한다.
          category3: product.category3,
          category4: product.category4,
        }),
      });
      const data = await res.json();
      if (!data.ok) { btn.textContent = "실패"; console.error(data.error); return; }
      // 평면도 SVG 교체 + 드래그 재바인딩
      if (planBox && data.svg_markup) {
        planBox.innerHTML = data.svg_markup;
        if (window.initFloorplanDrag) window.initFloorplanDrag();
        if (window.initFloorplanTooltip) window.initFloorplanTooltip();
        if (window.initFloorplanRotate) window.initFloorplanRotate();
      }
      btn.className = "btn btn-sm btn-success mt-auto add-btn";
      btn.textContent = "추가됨 ✓";
    } catch (err) {
      console.error(err);
      btn.textContent = "오류";
      btn.disabled = false;
    }
  }

  searchBtn.addEventListener("click", search);
  queryInput.addEventListener("keydown", (e) => { if (e.key === "Enter") search(); });
})();
