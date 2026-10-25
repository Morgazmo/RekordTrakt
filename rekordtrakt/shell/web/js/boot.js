// Theme and skin before the first paint, so the window never flashes the wrong colours. Shared with the Debug page.
try {
  const theme = localStorage.getItem("rt-theme"), skin = localStorage.getItem("rt-skin");
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  if (skin && skin !== "teal") document.documentElement.dataset.skin = skin;
} catch { /* storage blocked: system theme, default skin */ }
