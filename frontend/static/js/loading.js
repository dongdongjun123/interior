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

      // 이미 완료(✓)로 확정된 단계는 되돌리지 않는다.
      if (item.classList.contains("done")) {
        return;
      }

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
     * 서버가 세부 진행 상태를 실시간으로 알려주지는 않지만, 실제 파이프라인은
     * (layout 추출 → 자기교정 → SVG 렌더) 순으로 앞으로만 진행한다.
     * 그래서 체크리스트도 되돌아가지 않고 앞으로만 나아가다가,
     * 마지막 단계(평면도 생성)에서 fetch 완료를 기다린다.
     * - 지나온 단계는 ✓(done)로 확정, 현재 단계만 ●(active).
     * - Gemini 호출 2회가 대부분의 시간을 차지하므로 앞 단계는 여유 있게 배분.
     */
    const lastStep = checklistItems.length - 1;
    // 단계별 머무는 시간(ms): 업로드 확인은 짧게, 분석 단계는 Gemini 호출을 감안해 길게.
    const stepDurations = [900, 3200, 3200];

    function advance(step) {
      if (step > lastStep) {
        return; // 마지막 단계 도달 → 완료(fetch)까지 여기서 대기
      }
      // 지나온 단계를 done(✓)으로 확정
      for (let i = 0; i < step; i += 1) {
        const icon = checklistItems[i].querySelector(".check-icon");
        checklistItems[i].classList.remove("active");
        checklistItems[i].classList.add("done");
        if (icon) {
          icon.textContent = "✓";
        }
      }
      currentStep = step;
      showStep(step);

      if (step < lastStep) {
        stageTimer = window.setTimeout(
          () => advance(step + 1),
          stepDurations[step] || 2500
        );
      }
    }

    advance(0);
  }

  function showCompletedState() {
    if (stageTimer) {
      window.clearTimeout(stageTimer);
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
      window.clearTimeout(stageTimer);
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
