if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/sw.js");
}

window.addEventListener("pageshow", (event) => {
  if (event.persisted && window.location.pathname === "/lists") {
    window.location.reload();
  }
});

document.addEventListener("click", (event) => {
  const backButton = event.target.closest("[data-back-button]");
  if (backButton) {
    if (backButton.dataset.backUrl) {
      window.location.assign(backButton.dataset.backUrl);
    } else if (window.history.length > 1 && document.referrer.startsWith(window.location.origin)) {
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

  const moveToggle = event.target.closest("[data-item-move-toggle]");
  if (moveToggle) {
    const form = document.querySelector("[data-item-move-form]");
    if (form) {
      form.hidden = false;
      form.querySelector("select[name='wishlist_id']")?.focus();
    }
    return;
  }

  const moveCancel = event.target.closest("[data-item-move-cancel]");
  if (moveCancel) {
    const form = moveCancel.closest("[data-item-move-form]");
    if (form) {
      form.hidden = true;
    }
    return;
  }

  const categoryDialogOpen = event.target.closest("[data-category-dialog-open]");
  if (categoryDialogOpen) {
    const dialog = document.getElementById(categoryDialogOpen.dataset.categoryDialogOpen);
    if (dialog) {
      if (dialog.showModal) {
        dialog.showModal();
      } else {
        dialog.setAttribute("open", "");
      }
      dialog.querySelector("input[name='name']")?.focus();
    }
    return;
  }

  const dialogClose = event.target.closest("[data-dialog-close]");
  if (dialogClose) {
    dialogClose.closest("dialog")?.close();
    return;
  }

  if (event.target instanceof HTMLDialogElement) {
    event.target.close();
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
  const submitter = event.submitter?.closest("[data-confirm]");
  const form = event.target.closest("[data-confirm]");
  const confirmation = submitter?.dataset.confirm || form?.dataset.confirm;
  if (confirmation && !window.confirm(confirmation)) {
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
  const moveForm = document.querySelector("[data-item-move-form]:not([hidden])");
  if (moveForm) {
    moveForm.hidden = true;
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
