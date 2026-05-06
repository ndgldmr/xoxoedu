import react from "@vitejs/plugin-react";
import {defineConfig} from "vitest/config";

const vitestConfig = defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "src/**/*.spec.{ts,tsx}"],
  },
});

export default vitestConfig;
