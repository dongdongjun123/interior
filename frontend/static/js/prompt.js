// prompt.js — 태그 클릭 자동 입력 + AI 생성 요청
(function () {
  const textarea = document.getElementById("moodInput");
  const tagButtons = document.querySelectorAll(".tag-btn");
  const generateBtn = document.getElementById("generateBtn");
  const generateUrl = document.currentScript.dataset.generateUrl;
  const moodSearchUrl = document.currentScript.dataset.moodSearchUrl;
  const previewBox = document.getElementById("stylePreview");

  const activeTags = new Set();

  // ── Style Preview: 프롬프트 입력에 맞춰 유사 이미지 갱신 ──
  let searchTimer = null;

  function renderPreview(results) {
    if (!previewBox) return;
    if (!results || results.length === 0) return; // 결과 없으면 기존 유지
    previewBox.innerHTML = results
      .map(
        (r) =>
          `<div class="col-6"><div class="style-preview-item" style="height:160px;">
             <img src="${r.url}" alt="mood" style="width:100%;height:100%;object-fit:cover;border-radius:8px;">
           </div></div>`
      )
      .join("");
  }

  async function updatePreview(query) {
    if (!moodSearchUrl || !query.trim()) return;
    try {
      const res = await fetch(`${moodSearchUrl}?q=${encodeURIComponent(query)}`);
      const data = await res.json();
      if (data.ok) renderPreview(data.results);
    } catch (e) {
      /* 미리보기 실패는 조용히 무시 (핵심 흐름 아님) */
    }
  }

  function scheduleSearch() {
    // 입력이 멈추고 600ms 뒤 한 번만 검색 (디바운스)
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => updatePreview(textarea.value), 600);
  }

  if (textarea) textarea.addEventListener("input", scheduleSearch);

  tagButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const tag = btn.dataset.tag;
      btn.classList.toggle("active");

      if (activeTags.has(tag)) {
        activeTags.delete(tag);
      } else {
        activeTags.add(tag);
        // textarea에 자동 입력 (이미 들어있지 않을 때만)
        const current = textarea.value.trim();
        if (!current.includes(tag)) {
          textarea.value = current ? `${current}, ${tag}` : tag;
        }
      }
      scheduleSearch(); // 태그 변경 시에도 미리보기 갱신
    });
  });

  generateBtn.addEventListener("click", async () => {
    generateBtn.disabled = true;
    const originalText = generateBtn.textContent;
    generateBtn.textContent = "AI가 디자인 중입니다...";

    try {
      const res = await fetch(generateUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: textarea.value.trim(),
          tags: Array.from(activeTags),
        }),
      });
      const data = await res.json();

      if (data.ok) {
        window.location.href = data.redirect;
      } else {
        alert(data.error || "생성에 실패했어요. 다시 시도해주세요.");
        generateBtn.disabled = false;
        generateBtn.textContent = originalText;
      }
    } catch (err) {
      alert("네트워크 오류로 생성에 실패했어요.");
      generateBtn.disabled = false;
      generateBtn.textContent = originalText;
    }
  });
})();
