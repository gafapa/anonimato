"use strict";

for (const select of document.querySelectorAll("[data-language]")) {
  select.addEventListener("change", () => {
    const destination = select.value;
    if (/^\/(?:en\/|es\/|gl\/|fr\/|de\/|it\/|pt\/)?(?:privacy\/)?$/.test(destination)) {
      window.location.assign(destination);
    }
  });
}

for (const demo of document.querySelectorAll("[data-demo]")) {
  const button = demo.querySelector("[data-toggle]");
  const status = demo.querySelector("[data-status]");
  button.addEventListener("click", () => {
    const redacted = demo.dataset.redacted !== "true";
    demo.dataset.redacted = String(redacted);
    button.setAttribute("aria-pressed", String(redacted));
    button.textContent = redacted ? button.dataset.after : button.dataset.before;
    status.textContent = redacted ? button.dataset.statusAfter : button.dataset.statusBefore;
    for (const value of demo.querySelectorAll("[data-private]")) {
      value.textContent = redacted ? value.dataset.label : value.dataset.private;
    }
  });
}
