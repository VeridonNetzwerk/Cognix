import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: { DEFAULT: "#0b0d12", soft: "#11141b", muted: "#1a1f29" },
        border: "#252a35",
        fg: { DEFAULT: "#e6e9ef", muted: "#9aa3b2", dim: "#6b7280" },
        brand: { DEFAULT: "#5865F2", hover: "#4752c4" },
        success: "#4ade80",
        warning: "#f59e0b",
        danger: "#ef4444",
      },
      borderRadius: { lg: "12px", xl: "16px" },
    },
  },
  plugins: [],
};

export default config;
