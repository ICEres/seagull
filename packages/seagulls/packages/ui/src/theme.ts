export type ThemePreference = "light" | "dark" | "system";

// Unified storage key shared by the landing page and the web app.
// NOTE: the web app previously stored its preference under "seagull.web.theme";
// switching to the shared key means web users' stored theme preference resets
// once (they fall back to the OS preference until they toggle again).
export const THEME_KEY = "seagulls-theme";

export function loadThemePreference(): ThemePreference {
  const stored = window.localStorage.getItem(THEME_KEY);
  if (stored === "light" || stored === "dark") {
    return stored;
  }
  return "system";
}

export function saveThemePreference(preference: ThemePreference): void {
  if (preference === "system") {
    window.localStorage.removeItem(THEME_KEY);
    return;
  }
  window.localStorage.setItem(THEME_KEY, preference);
}

export function systemPrefersDark(): boolean {
  return Boolean(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
}

export function resolveTheme(preference: ThemePreference): "light" | "dark" {
  if (preference === "system") {
    return systemPrefersDark() ? "dark" : "light";
  }
  return preference;
}

export function applyTheme(preference: ThemePreference): "light" | "dark" {
  const resolved = resolveTheme(preference);
  document.documentElement.classList.toggle("dark", resolved === "dark");
  return resolved;
}
