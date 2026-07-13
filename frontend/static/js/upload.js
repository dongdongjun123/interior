// upload.js — STEP 1 사진 업로드
(function () {
  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");
  const chooseFileBtn = document.getElementById("chooseFileBtn");
  const previewCard = document.getElementById("previewCard");
  const previewThumb = document.getElementById("previewThumb");
  const previewName = document.getElementById("previewName");
  const previewSize = document.getElementById("previewSize");
  const removeFileBtn = document.getElementById("removeFileBtn");
  const nextBtn = document.getElementById("nextBtn");
  const errorEl = document.getElementById("uploadError");

  const scriptTag = document.currentScript;
  const uploadUrl = scriptTag.dataset.uploadUrl;

  const MAX_SIZE = 20 * 1024 * 1024; // 20MB
  const ALLOWED_TYPES = ["image/jpeg", "image/png"];

  let selectedFile = null;

  function showError(msg) {
    errorEl.textContent = msg;
    errorEl.classList.remove("d-none");
  }

  function clearError() {
    errorEl.classList.add("d-none");
    errorEl.textContent = "";
  }

  function formatSize(bytes) {
    return (bytes / (1024 * 1024)).toFixed(1) + "MB";
  }

  function handleFile(file) {
    clearError();
    if (!file) return;

    if (!ALLOWED_TYPES.includes(file.type)) {
      showError("JPG, PNG 파일만 업로드할 수 있어요.");
      return;
    }
    if (file.size > MAX_SIZE) {
      showError("파일 크기는 최대 20MB까지 가능해요.");
      return;
    }

    selectedFile = file;

    const reader = new FileReader();
    reader.onload = (e) => {
      previewThumb.src = e.target.result;
    };
    reader.readAsDataURL(file);

    previewName.textContent = file.name;
    previewSize.textContent = formatSize(file.size);
    previewCard.classList.remove("d-none");
    nextBtn.disabled = false;
  }

  chooseFileBtn.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", (e) => handleFile(e.target.files[0]));

  ["dragenter", "dragover"].forEach((evt) => {
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((evt) => {
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.classList.remove("dragover");
    });
  });
  dropZone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files[0];
    handleFile(file);
  });

  removeFileBtn.addEventListener("click", () => {
    selectedFile = null;
    fileInput.value = "";
    previewCard.classList.add("d-none");
    nextBtn.disabled = true;
  });

  nextBtn.addEventListener("click", async () => {
    if (!selectedFile) return;
    nextBtn.disabled = true;
    nextBtn.textContent = "업로드 중...";

    try {
      const formData = new FormData();
      formData.append("photo", selectedFile);

      const res = await fetch(uploadUrl, { method: "POST", body: formData });
      const data = await res.json();

      if (data.ok) {
        window.location.href = data.redirect;
      } else {
        showError(data.error || "업로드에 실패했어요.");
        nextBtn.disabled = false;
        nextBtn.textContent = "다음";
      }
    } catch (err) {
      showError("네트워크 오류로 업로드에 실패했어요.");
      nextBtn.disabled = false;
      nextBtn.textContent = "다음";
    }
  });
})();
