import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";

const projectRoot = fileURLToPath(new URL("../..", import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, projectRoot, "");
  const serviceUrl = env.ASSESSMENT_SERVICE_URL || "http://127.0.0.1:8080";
  const serviceToken = env.ASSESSMENT_SERVICE_TOKEN;
  return {
    server: {
      port: 5173,
      proxy: {
        "/backend": {
          target: serviceUrl,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/backend/, ""),
          headers: serviceToken
            ? { Authorization: `Bearer ${serviceToken}` }
            : undefined,
        },
      },
    },
  };
});
