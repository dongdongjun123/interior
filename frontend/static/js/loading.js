(function () {
  const currentScript = document.currentScript;

  const nextUrl = currentScript
    ? currentScript.dataset.nextUrl
    : "";

  const loadingTitle = document.getElementById("loadingTitle");
  const loadingDescription = document.getElementById(
    "loadingDescription"
  );
  const progressBar = document.getElementById("progressBar");
  const progressText = document.getElementById("progressText");
  const checklistItems = Array.from(
    document.querySelectorAll(".checklist li")
  );
  const loadingError = document.getElementById("loadingError");
  const loadingErrorMessage = document.getElementById(
    "loadingErrorMessage"
  );
  const retryButton = document.getElementById("retryButton");

  let currentStep = 0;
  let stageTimer = null;

  function showStep(stepIndex) {
    checklistItems.forEach((item, index) => {
      const icon = item.querySelector(".check-icon");

      item.classList.remove("active");

      if (index === stepIndex) {
        item.classList.add("active");

        if (icon) {
          icon.textContent = "●";
        }
      } else if (icon) {
        icon.textContent = "○";
      }
    });
  }

  function startStepAnimation() {
    if (checklistItems.length === 0) {
      return;
    }

    showStep(currentStep);

    /*
     * 실제 세부 분석 상태를 서버에서 받는 구조는 아직 없으므로,
     * 분석 항목을 순서대로 강조하여 작업 중임을 안내한다.
     */
    stageTimer = window.setInterval(() => {
      currentStep = (currentStep + 1) % checklistItems.length;
      showStep(currentStep);
    }, 1400);
  }

  function showCompletedState() {
    if (stageTimer) {
      window.clearInterval(stageTimer);
    }

    checklistItems.forEach((item) => {
      const icon = item.querySelector(".check-icon");

      item.classList.remove("active");
      item.classList.add("done");

      if (icon) {
        icon.textContent = "✓";
      }
    });

    if (progressBar) {
      progressBar.classList.add("finished");
    }

    if (loadingTitle) {
      loadingTitle.textContent = "평면도 생성이 완료되었습니다.";
    }

    if (loadingDescription) {
      loadingDescription.textContent =
        "평면도 확인 화면으로 이동하고 있어요.";
    }

    if (progressText) {
      progressText.textContent = "잠시만 기다려 주세요.";
    }
  }

  function showError(message) {
    if (stageTimer) {
      window.clearInterval(stageTimer);
    }

    if (progressBar) {
      progressBar.classList.add("error");
    }

    if (loadingTitle) {
      loadingTitle.textContent = "평면도를 생성하지 못했습니다.";
    }

    if (loadingDescription) {
      loadingDescription.textContent =
        "잠시 후 다시 시도해 주세요.";
    }

    if (progressText) {
      progressText.textContent = "";
    }

    if (loadingErrorMessage) {
      loadingErrorMessage.textContent =
        message || "평면도 생성 중 오류가 발생했습니다.";
    }

    if (loadingError) {
      loadingError.hidden = false;
    }
  }

  async function loadFloorplan() {
    if (!nextUrl) {
      showError("평면도 화면 주소를 찾을 수 없습니다.");
      return;
    }

    try {
      /*
       * /floorplan 요청이 처리되는 동안 현재 로딩 화면은 유지된다.
       * Model1 처리가 완료되면 반환된 평면도 HTML로 화면을 교체한다.
       */
      const response = await fetch(nextUrl, {
        method: "GET",
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
        },
      });

      if (!response.ok) {
        throw new Error(
          `평면도 요청에 실패했습니다. (${response.status})`
        );
      }

      const html = await response.text();

      showCompletedState();

      window.setTimeout(() => {
        const responseUrl = response.url || nextUrl;

        window.history.replaceState(
          null,
          "",
          responseUrl
        );

        document.open();
        document.write(html);
        document.close();
      }, 500);
    } catch (error) {
      console.error("평면도 생성 실패:", error);

      showError(
        "평면도를 불러오지 못했습니다. 네트워크 상태를 확인해 주세요."
      );
    }
  }

  if (retryButton) {
    retryButton.addEventListener("click", () => {
      window.location.reload();
    });
  }

  startStepAnimation();

  /*
   * 로딩 화면이 먼저 표시된 뒤 실제 평면도 요청을 시작한다.
   */
  window.setTimeout(loadFloorplan, 300);
})();
