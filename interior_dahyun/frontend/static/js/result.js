// result.js — 저장 / 공유 / 이미지 확대 (mock)
(function () {
  const saveBtn = document.getElementById("saveBtn");
  const shareBtn = document.getElementById("shareBtn");
  const resultImage = document.querySelector(".result-image");

  if (saveBtn) {
    saveBtn.addEventListener("click", () => {
      saveBtn.textContent = "저장됨 ✓";
      setTimeout(() => (saveBtn.textContent = "저장"), 1500);
      // 실제 서비스에서는 여기서 /save 같은 API를 호출해 '내 디자인'에 저장
    });
  }

  if (shareBtn) {
    shareBtn.addEventListener("click", async () => {
      const shareUrl = window.location.href;
      try {
        await navigator.clipboard.writeText(shareUrl);
        shareBtn.textContent = "링크 복사됨 ✓";
      } catch (err) {
        shareBtn.textContent = "복사 실패";
      }
      setTimeout(() => (shareBtn.textContent = "공유"), 1500);
    });
  }

  if (resultImage && resultImage.tagName === "IMG") {
    resultImage.style.cursor = "zoom-in";
    resultImage.addEventListener("click", () => {
      resultImage.classList.toggle("result-image-zoomed");
    });
  }
})();
