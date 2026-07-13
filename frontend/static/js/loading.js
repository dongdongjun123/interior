// loading.js — AI 분석 로딩 애니메이션
(function () {
  const progressBar = document.getElementById("progressBar");
  const progressPercent = document.getElementById("progressPercent");
  const checklistItems = document.querySelectorAll(".checklist li");
  const nextUrl = document.currentScript.dataset.nextUrl;

  const totalSteps = checklistItems.length;
  let step = 0;
  let progress = 0;

  function tick() {
    progress += 2;
    progressBar.style.width = progress + "%";
    progressPercent.textContent = progress + "%";

    const expectedStep = Math.min(
      totalSteps - 1,
      Math.floor((progress / 100) * totalSteps)
    );

    if (expectedStep > step) {
      checklistItems[step].classList.remove("active");
      checklistItems[step].classList.add("done");
      checklistItems[step].querySelector(".check-icon").textContent = "✔";
      step = expectedStep;
    }
    checklistItems[step].classList.add("active");

    if (progress >= 100) {
      checklistItems.forEach((li) => {
        li.classList.add("done");
        li.classList.remove("active");
        li.querySelector(".check-icon").textContent = "✔";
      });
      clearInterval(intervalId);
      setTimeout(() => {
        window.location.href = nextUrl;
      }, 500);
      return;
    }
  }

  const intervalId = setInterval(tick, 60);
})();
