// A popover under a header button (Theme, what needs attention): opens on its click, closes on a click elsewhere
// or Escape. Both header popovers use it, so they look and behave alike.
export function popover(button, pop, align = "right") {
  const place = () => {
    const r = button.getBoundingClientRect();
    pop.style.top = `${r.bottom + 6}px`;
    const left = align === "left" ? r.left : r.right - pop.offsetWidth;
    pop.style.left = `${Math.max(8, Math.min(window.innerWidth - pop.offsetWidth - 8, left))}px`;
  };
  const api = {
    open() { pop.hidden = false; place(); button.setAttribute("aria-expanded", "true"); },
    close() { pop.hidden = true; button.setAttribute("aria-expanded", "false"); },
    toggle() { if (pop.hidden) api.open(); else api.close(); },
  };
  button.addEventListener("click", (e) => { e.stopPropagation(); api.toggle(); });
  document.addEventListener("pointerdown", (e) => {
    if (!pop.hidden && !pop.contains(e.target) && !button.contains(e.target)) api.close();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pop.hidden) api.close(); });
  window.addEventListener("resize", () => { if (!pop.hidden) place(); });
  return api;
}
