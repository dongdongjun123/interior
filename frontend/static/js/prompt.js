// 프롬프트 입력 → 추천 이미지 검색 → 이미지 선택 → 스타일 저장
(function () {
  const textarea = document.getElementById("moodInput");
  const tagButtons = document.querySelectorAll(".tag-btn");
  const generateBtn = document.getElementById("generateBtn");
  const previewBox = document.getElementById("stylePreview");

  const generateUrl = document.currentScript.dataset.generateUrl;
  const moodSearchUrl = document.currentScript.dataset.moodSearchUrl;

  if (!textarea || !generateBtn) return;

  const activeTags = new Set();

  // 사용자가 선택한 추천 이미지 경로
  let selectedImage = "";

  // 실시간 검색을 너무 자주 실행하지 않기 위한 타이머
  let searchTimer = null;

  function clearSelection() {
    selectedImage = "";

    if (!previewBox) return;

    previewBox.querySelectorAll(".mood-option").forEach((option) => {
      option.classList.remove("selected");
      option.setAttribute("aria-selected", "false");
      option.style.outline = "";
      option.style.outlineOffset = "";
      option.style.boxShadow = "";
    });
  }

  function selectMoodOption(option) {
    if (!previewBox || !option) return;

    clearSelection();

    selectedImage = option.dataset.imagePath || "";

    option.classList.add("selected");
    option.setAttribute("aria-selected", "true");

    // 선택된 이미지 표시
    option.style.outline = "3px solid #212529";
    option.style.outlineOffset = "2px";
    option.style.boxShadow = "0 0 0 4px rgba(33, 37, 41, 0.15)";
  }

  function renderPreview(results) {
    if (!previewBox) return;

    clearSelection();

    if (!results || results.length === 0) {
      previewBox.innerHTML = `
        <div class="col-12">
          <p class="text-muted small mb-0">
            입력한 문구와 유사한 이미지를 찾지 못했습니다.
          </p>
        </div>
      `;
      return;
    }

    previewBox.innerHTML = results
      .map(
        (result) => `
          <div class="col-6">
            <div
              class="style-preview-item mood-option"
              data-image-path="${result.path}"
              role="button"
              tabindex="0"
              aria-selected="false"
              style="height:160px; cursor:pointer;"
            >
              <img
                src="${result.url}"
                alt="추천 인테리어 이미지"
                style="width:100%; height:100%; object-fit:cover; border-radius:8px;"
              >
            </div>
          </div>
        `
      )
      .join("");
  }

  async function updatePreview(query) {
    if (!moodSearchUrl || !query.trim()) return;

    try {
      const response = await fetch(
        `${moodSearchUrl}?q=${encodeURIComponent(query)}`
      );

      const data = await response.json();

      if (data.ok) {
        renderPreview(data.results);
      }
    } catch (error) {
      console.error("추천 이미지 검색 실패:", error);
    }
  }

  function scheduleSearch() {
    clearTimeout(searchTimer);

    searchTimer = setTimeout(() => {
      updatePreview(textarea.value);
    }, 600);
  }

  // 문구가 바뀌면 추천 이미지 다시 검색
  textarea.addEventListener("input", scheduleSearch);

  // 태그 선택
  tagButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const tag = button.dataset.tag;

      button.classList.toggle("active");

      if (activeTags.has(tag)) {
        activeTags.delete(tag);
      } else {
        activeTags.add(tag);

        const current = textarea.value.trim();

        if (!current.includes(tag)) {
          textarea.value = current ? `${current}, ${tag}` : tag;
        }
      }

      scheduleSearch();
    });
  });

  // 추천 이미지 마우스 클릭
  if (previewBox) {
    previewBox.addEventListener("click", (event) => {
      const option = event.target.closest(".mood-option");

      if (option) {
        selectMoodOption(option);
      }
    });

    // Enter 또는 Space 키로도 선택 가능
    previewBox.addEventListener("keydown", (event) => {
      const option = event.target.closest(".mood-option");

      if (!option) return;

      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectMoodOption(option);
      }
    });
  }

  // 다음 단계로 이동
  generateBtn.addEventListener("click", async () => {
    const promptText = textarea.value.trim();

    if (!promptText) {
      alert("원하는 인테리어 분위기를 입력해 주세요.");
      textarea.focus();
      return;
    }

    if (!selectedImage) {
      alert("추천 이미지 중 하나를 선택해 주세요.");
      return;
    }

    generateBtn.disabled = true;

    const originalText = generateBtn.textContent;
    generateBtn.textContent = "스타일 저장 중...";

    try {
      const response = await fetch(generateUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          prompt: promptText,
          tags: Array.from(activeTags),
          selected_image: selectedImage,
        }),
      });

      const data = await response.json();

      if (data.ok) {
        window.location.href = data.redirect;
      } else {
        alert(
          data.error ||
            "스타일 저장에 실패했어요. 다시 시도해 주세요."
        );

        generateBtn.disabled = false;
        generateBtn.textContent = originalText;
      }
    } catch (error) {
      console.error(error);

      alert("네트워크 오류로 스타일 저장에 실패했어요.");

      generateBtn.disabled = false;
      generateBtn.textContent = originalText;
    }
  });
})();
