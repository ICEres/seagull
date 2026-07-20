export type ThemePreference = "light" | "dark" | "system";

const THEME_KEY = "seagull.web.theme";

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
