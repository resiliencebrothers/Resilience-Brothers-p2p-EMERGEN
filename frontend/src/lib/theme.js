// iter241 — preferencia de tema (oscuro por defecto, claro opcional).
const KEY = "rb_theme";

export function getTheme() {
  try { return localStorage.getItem(KEY) === "light" ? "light" : "dark"; }
  catch { return "dark"; }
}

export function applyTheme(theme) {
  document.documentElement.classList.toggle("light", theme === "light");
}

export function setTheme(theme) {
  try { localStorage.setItem(KEY, theme); } catch { /* bloqueado */ }
  applyTheme(theme);
}
