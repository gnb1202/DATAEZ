import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const config = [
  ...nextVitals,
  ...nextTypescript,
  // Existing panels synchronously reset dependent form state. Keep those
  // compiler diagnostics visible without blocking this workspace migration.
  {
    files: ["components/dashboard/attribute-restore-panel.tsx", "components/dashboard/event-review-panel.tsx"],
    rules: { "react-hooks/set-state-in-effect": "warn" },
  },
  {
    files: ["components/ui/sidebar.tsx"],
    rules: { "react-hooks/purity": "warn" },
  },
  {
    rules: {
      "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
      "@typescript-eslint/no-explicit-any": "off",
      "react/no-unescaped-entities": "off",
    },
  },
];

export default config;
