// STEP 2: 방 사진과 크기 정보 업로드
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

  const roomWidthInput = document.getElementById("roomWidth");
  const roomDepthInput = document.getElementById("roomDepth");
  const ceilingHeightInput = document.getElementById("ceilingHeight");

  const scriptTag = document.currentScript;
  const uploadUrl = scriptTag.dataset.uploadUrl;

  const MAX_SIZE = 20 * 1024 * 1024;
  const ALLOWED_TYPES = ["image/jpeg", "image/png"];

  let selectedFile = null;

  function showError(message) {
    errorEl.textContent = message;
    errorEl.classList.remove("d-none");
  }

  function clearError() {
    errorEl.classList.add("d-none");
    errorEl.textContent = "";
  }

  function formatSize(bytes) {
    return (bytes / (1024 * 1024)).toFixed(1) + "MB";
  }

  function getDimensions() {
    return {
      roomWidth: Number.parseFloat(roomWidthInput.value),
      roomDepth: Number.parseFloat(roomDepthInput.value),
      ceilingHeight: Number.parseFloat(ceilingHeightInput.value),
    };
  }

  function getDimensionState() {
    const rawValues = [
      roomWidthInput.value.trim(),
      roomDepthInput.value.trim(),
      ceilingHeightInput.value.trim(),
    ];

    const allEmpty = rawValues.every((value) => value === "");

    if (allEmpty) {
      return {
        valid: true,
        hasDimensions: false,
      };
    }

    const allFilled = rawValues.every((value) => value !== "");
    const dimensions = getDimensions();

    const allValid =
      allFilled &&
      Number.isFinite(dimensions.roomWidth) &&
      dimensions.roomWidth >= 0.1 &&
      Number.isFinite(dimensions.roomDepth) &&
      dimensions.roomDepth >= 0.1 &&
      Number.isFinite(dimensions.ceilingHeight) &&
      dimensions.ceilingHeight >= 0.1;

    return {
      valid: allValid,
      hasDimensions: allValid,
    };
  }

  function updateNextButton() {
    nextBtn.disabled = !selectedFile;
  }

  function handleFile(file) {
    clearError();

    if (!file) return;

    if (!ALLOWED_TYPES.includes(file.type)) {
      showError("JPG 또는 PNG 파일만 업로드할 수 있어요.");
      return;
    }

    if (file.size > MAX_SIZE) {
      showError("파일 크기는 최대 20MB까지 가능해요.");
      return;
    }

    selectedFile = file;

    const reader = new FileReader();

    reader.onload = (event) => {
      previewThumb.src = event.target.result;
    };

    reader.readAsDataURL(file);

    previewName.textContent = file.name;
    previewSize.textContent = formatSize(file.size);
    previewCard.classList.remove("d-none");

    updateNextButton();
  }

  chooseFileBtn.addEventListener("click", () => {
    fileInput.click();
  });

  fileInput.addEventListener("change", (event) => {
    handleFile(event.target.files[0]);
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.remove("dragover");
    });
  });

  dropZone.addEventListener("drop", (event) => {
    const file = event.dataTransfer.files[0];
    handleFile(file);
  });

  removeFileBtn.addEventListener("click", () => {
    selectedFile = null;
    fileInput.value = "";
    previewCard.classList.add("d-none");
    updateNextButton();
  });

  [roomWidthInput, roomDepthInput, ceilingHeightInput].forEach((input) => {
    input.addEventListener("input", () => {
      clearError();
      updateNextButton();
    });
  });

  nextBtn.addEventListener("click", async () => {
    if (!selectedFile) {
      showError("방 사진을 선택해 주세요.");
      return;
    }

    const dimensionState = getDimensionState();

    if (!dimensionState.valid) {
      showError("방 크기는 세 항목을 모두 입력하거나 모두 비워 주세요.");
      return;
    }

    const { roomWidth, roomDepth, ceilingHeight } = getDimensions();

    nextBtn.disabled = true;
    nextBtn.textContent = "업로드 중...";

    try {
      const formData = new FormData();

      formData.append("photo", selectedFile);
      if (dimensionState.hasDimensions) {
        formData.append("room_width", roomWidth.toString());
        formData.append("room_depth", roomDepth.toString());
        formData.append("ceiling_height", ceilingHeight.toString());
      }

      const response = await fetch(uploadUrl, {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (data.ok) {
        window.location.href = data.redirect;
      } else {
        showError(data.error || "업로드에 실패했어요.");
        nextBtn.textContent = "다음";
        updateNextButton();
      }
    } catch (error) {
      console.error(error);
      showError("네트워크 오류로 업로드에 실패했어요.");
      nextBtn.textContent = "다음";
      updateNextButton();
    }
  });

  updateNextButton();
})();
