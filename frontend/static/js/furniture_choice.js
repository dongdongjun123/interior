(function () {
  const choiceCards =
    document.querySelectorAll(
      "[data-choice-card]"
    );

  const decisionInputs =
    document.querySelectorAll(
      'input[type="radio"][name^="decision_"]'
    );

  const purchaseInputs =
    document.querySelectorAll(
      'input[name="purchase_items"]'
    );

  const keepCount =
    document.getElementById("keepCount");

  const removeCount =
    document.getElementById("removeCount");

  const replaceCount =
    document.getElementById("replaceCount");

  const purchaseCount =
    document.getElementById("purchaseCount");

  function updateDecisionSummary() {
    let keep = 0;
    let remove = 0;
    let replace = 0;

    choiceCards.forEach((card) => {
      const selected = card.querySelector(
        'input[type="radio"]:checked'
      );

      card.classList.remove(
        "is-keep",
        "is-remove",
        "is-replace"
      );

      if (!selected) {
        return;
      }

      if (selected.value === "remove") {
        remove += 1;
        card.classList.add("is-remove");
      } else if (selected.value === "replace") {
        replace += 1;
        card.classList.add("is-replace");

        const matchingPurchase = document.querySelector(
          'input[name="purchase_items"][value="' +
          selected.dataset.itemType +
          '"]'
        );

        if (matchingPurchase) {
          matchingPurchase.checked = true;
        }
      } else {
        keep += 1;
        card.classList.add("is-keep");
      }
    });

    if (keepCount) {
      keepCount.textContent = keep;
    }

    if (removeCount) {
      removeCount.textContent = remove;
    }

    if (replaceCount) {
      replaceCount.textContent = replace;
    }

    updatePurchaseSummary();
  }

  function updatePurchaseSummary() {
    const selectedCount = Array.from(
      purchaseInputs
    ).filter(
      (input) => input.checked
    ).length;

    if (purchaseCount) {
      purchaseCount.textContent =
        selectedCount;
    }
  }

  decisionInputs.forEach((input) => {
    input.addEventListener(
      "change",
      updateDecisionSummary
    );
  });

  purchaseInputs.forEach((input) => {
    input.addEventListener(
      "change",
      updatePurchaseSummary
    );
  });

  updateDecisionSummary();
  updatePurchaseSummary();
})();
