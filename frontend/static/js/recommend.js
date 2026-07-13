// 가구 클릭 -> /recommend API 호출 -> 상품 추천 Drawer 채우기
(function () {
  const drawerEl = document.getElementById("furnitureDrawer");
  const drawerTitle = document.getElementById("drawerTitle");
  const drawerBody = document.getElementById("drawerBody");
  const recommendUrl = document.currentScript.dataset.recommendUrl;

  if (!drawerEl) return;

  function renderLoading() {
    drawerBody.innerHTML = `<div class="drawer-loading">불러오는 중...</div>`;
  }

  function renderError(msg) {
    drawerBody.innerHTML = `<div class="drawer-loading">${msg}</div>`;
  }

  function formatPrice(price) {
    if (!price) return "가격 정보 없음";
    return `${Number(price).toLocaleString()}원`;
  }

  function renderItem(item) {
    const rating = item.rating || 4;
    const stars = "★".repeat(Math.round(rating)) + "☆".repeat(5 - Math.round(rating));

    const imageHtml = item.image
      ? `
        <a 
          href="${item.link || '#'}" 
          target="_blank" 
          rel="noopener noreferrer"
          style="display:block; width:100%; height:100%;"
        >
          <img 
            src="${item.image}" 
            alt="${item.name}" 
            style="width:100%; height:100%; object-fit:cover; border-radius:18px; cursor:pointer;"
          >
        </a>
      `
      : `<span class="text-muted">상품 사진 없음</span>`;

    const similarHtml = (item.similar || [])
      .map(
        (s) => `
        <div class="col-4">
          <a 
            href="${s.link || '#'}" 
            target="_blank" 
            rel="noopener noreferrer"
            class="text-decoration-none text-dark"
          >
            <div class="similar-thumb border d-flex flex-column align-items-center justify-content-center p-2" style="height:130px; overflow:hidden;">
              ${
                s.image
                  ? `<img src="${s.image}" alt="${s.name}" style="width:100%; height:70px; object-fit:cover; border-radius:10px; margin-bottom:6px;">`
                  : `<span class="text-muted small">사진 없음</span>`
              }
              <span class="text-muted small">${s.shop || "쇼핑몰"}</span>
              <small class="fw-semibold">${formatPrice(s.price)}</small>
            </div>
          </a>
        </div>`
      )
      .join("");

    drawerBody.innerHTML = `
      <div class="drawer-thumb border d-flex align-items-center justify-content-center mb-3" style="height:180px; overflow:hidden; border-radius:20px;">
        ${imageHtml}
      </div>

      <p class="mb-1">${stars}</p>
      <p class="drawer-price fw-bold mb-1">${formatPrice(item.price)}</p>
      <p class="text-muted small mb-4">${item.shop || ""}</p>

      <h6 class="mb-2">비슷한 상품</h6>
      <div class="row g-2 mb-4">${similarHtml}</div>

      <a 
        href="${item.link || '#'}" 
        target="_blank" 
        rel="noopener noreferrer"
        class="btn btn-dark rounded-pill w-100 buy-btn"
      >
        구매하기
      </a>
    `;
  }

  drawerEl.addEventListener("show.bs.offcanvas", async (event) => {
    const trigger = event.relatedTarget;
    const itemId = trigger ? trigger.dataset.itemId : null;

    renderLoading();
    drawerTitle.textContent = "상품 정보";

    if (!itemId) {
      renderError("가구 정보를 찾을 수 없어요.");
      return;
    }

    try {
      const res = await fetch(`${recommendUrl}?item=${encodeURIComponent(itemId)}`);
      const data = await res.json();

      if (data.ok) {
        drawerTitle.textContent = data.item.name;
        renderItem(data.item);
      } else {
        renderError(data.error || "상품 정보를 불러오지 못했어요.");
      }
    } catch (err) {
      console.error(err);
      renderError("네트워크 오류가 발생했어요.");
    }
  });
})();