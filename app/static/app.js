if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/sw.js");
}

document.addEventListener("click", (event) => {
  const backButton = event.target.closest("[data-back-button]");
  if (backButton) {
    if (window.history.length > 1 && document.referrer.startsWith(window.location.origin)) {
      window.history.back();
    } else {
      window.location.assign("/dashboard");
    }
    return;
  }

  const editToggle = event.target.closest("[data-list-edit-toggle]");
  if (editToggle) {
    const form = document.querySelector("[data-list-edit-form]");
    if (form) {
      form.hidden = false;
      form.querySelector("input[name='name']")?.focus();
    }
    return;
  }

  const editCancel = event.target.closest("[data-list-edit-cancel]");
  if (editCancel) {
    const form = editCancel.closest("[data-list-edit-form]");
    if (form) {
      form.hidden = true;
    }
    return;
  }

  const actionToggle = event.target.closest("[data-card-actions-toggle]");
  if (actionToggle) {
    const card = actionToggle.closest("[data-longpress-card]");
    if (card) {
      const isOpen = card.classList.contains("actions-open");
      closeListActions();
      card.classList.toggle("actions-open", !isOpen);
    }
    return;
  }

  const openCard = document.querySelector("[data-longpress-card].actions-open");
  if (openCard && !event.target.closest("[data-longpress-card].actions-open")) {
    closeListActions();
  }

  const longpressLink = event.target.closest("[data-longpress-link]");
  const longpressCard = longpressLink?.closest("[data-longpress-card]");
  if (longpressCard?.dataset.longpressOpened === "true") {
    event.preventDefault();
    longpressCard.dataset.longpressOpened = "false";
    return;
  }

  const button = event.target.closest("[data-next-sort-dir]");
  if (!button || !button.form) {
    return;
  }
  button.form.sort_dir.value = button.dataset.nextSortDir;
  button.form.submit();
});

document.addEventListener("submit", (event) => {
  const form = event.target.closest("[data-confirm]");
  if (form && !window.confirm(form.dataset.confirm)) {
    event.preventDefault();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") {
    return;
  }
  closeListActions();
  const form = document.querySelector("[data-list-edit-form]:not([hidden])");
  if (form) {
    form.hidden = true;
  }
});

let longpressTimer = null;
let longpressStart = null;

document.addEventListener("pointerdown", (event) => {
  const card = event.target.closest("[data-longpress-card]");
  if (!card || event.target.closest("button, input, select, textarea, form")) {
    return;
  }
  longpressStart = { x: event.clientX, y: event.clientY, card };
  longpressTimer = window.setTimeout(() => {
    closeListActions();
    card.classList.add("actions-open");
    card.dataset.longpressOpened = "true";
    longpressTimer = null;
  }, 560);
});

document.addEventListener("pointermove", (event) => {
  if (!longpressTimer || !longpressStart) {
    return;
  }
  const moved = Math.hypot(event.clientX - longpressStart.x, event.clientY - longpressStart.y);
  if (moved > 10) {
    clearLongpressTimer();
  }
});

document.addEventListener("pointerup", clearLongpressTimer);
document.addEventListener("pointercancel", clearLongpressTimer);

document.addEventListener("change", (event) => {
  const input = event.target.closest("[data-submit-on-change]");
  if (input && input.form) {
    input.form.submit();
  }
});

function clearLongpressTimer() {
  if (longpressTimer) {
    window.clearTimeout(longpressTimer);
  }
  longpressTimer = null;
  longpressStart = null;
}

function closeListActions() {
  document.querySelectorAll("[data-longpress-card].actions-open").forEach((card) => {
    card.classList.remove("actions-open");
  });
}
