// prompt.js — 태그 클릭 자동 입력 + AI 생성 요청
(function () {
  const textarea = document.getElementById("moodInput");
  const tagButtons = document.querySelectorAll(".tag-btn");
  const generateBtn = document.getElementById("generateBtn");
  const generateUrl = document.currentScript.dataset.generateUrl;

  const activeTags = new Set();

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
