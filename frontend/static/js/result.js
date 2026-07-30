// result.js — 저장 / 공유
(function () {
  const saveBtn = document.getElementById("saveBtn");
  const shareBtn = document.getElementById("shareBtn");

  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      const originalText = saveBtn.textContent;
      saveBtn.disabled = true;
      saveBtn.textContent = "저장 중...";

      try {
        const modifiedSvg = document.querySelector("#modifiedPlanBox svg");
        let svgMarkup = "";
        if (modifiedSvg) {
          const snapshot = modifiedSvg.cloneNode(true);
          snapshot.removeAttribute("data-drag-bound");
          snapshot.removeAttribute("data-edit-enabled");
          snapshot.classList.remove("floorplan-dragging", "floorplan-edit-mode");
          snapshot.querySelectorAll("[data-draggable]").forEach((item) => {
            item.style.opacity = "1";
          });
          svgMarkup = snapshot.outerHTML;
        }

        const response = await fetch(saveBtn.dataset.saveUrl, {
          method: "POST",
          headers: {
            "Accept": "application/json",
            "Content-Type": "application/json",
          },
          credentials: "same-origin",
          body: JSON.stringify({
            modified_svg: svgMarkup,
          }),
        });

        if (response.status === 401) {
          const loginUrl = saveBtn.dataset.loginUrl || "/login";
          window.location.href =
            loginUrl + "?next=" + encodeURIComponent(window.location.pathname);
          return;
        }

        const data = await response.json();
        if (!response.ok || !data.ok) {
          throw new Error(data.error || "save_failed");
        }

        saveBtn.textContent = "저장됨 ✓";
      } catch (error) {
        console.error(error);
        saveBtn.textContent = "저장 실패";
      } finally {
        window.setTimeout(() => {
          saveBtn.textContent = originalText;
          saveBtn.disabled = false;
        }, 1500);
      }
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

})();
