if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/sw.js");
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-next-sort-dir]");
  if (!button || !button.form) {
    return;
  }
  button.form.sort_dir.value = button.dataset.nextSortDir;
  button.form.submit();
});

document.addEventListener("change", (event) => {
  const input = event.target.closest("[data-submit-on-change]");
  if (input && input.form) {
    input.form.submit();
  }
});
