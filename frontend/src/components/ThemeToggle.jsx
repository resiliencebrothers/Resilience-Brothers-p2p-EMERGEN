import { useState } from "react";
import { Sun, Moon } from "lucide-react";
import { getTheme, setTheme } from "@/lib/theme";

// iter241 — alterna modo claro/oscuro (persistido en localStorage).
export function ThemeToggle({ testid = "theme-toggle" }) {
  const [theme, setLocal] = useState(getTheme());
  const next = theme === "light" ? "dark" : "light";
  return (
    <button
      type="button"
      data-testid={testid}
      aria-label={next === "light" ? "Modo claro" : "Modo oscuro"}
      title={next === "light" ? "Modo claro" : "Modo oscuro"}
      onClick={() => { setTheme(next); setLocal(next); }}
      className="flex items-center justify-center border border-white/10 hover:border-[#8B5CF6]/60 text-neutral-400 hover:text-[#8B5CF6] px-3 py-2 transition-colors"
    >
      {theme === "light" ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
    </button>
  );
}
