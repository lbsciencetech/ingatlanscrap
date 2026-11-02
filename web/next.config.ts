import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server (.next/standalone/server.js) for the Docker image.
  output: "standalone",
  // The MCP SDK spawns child processes: keep it out of the bundle.
  serverExternalPackages: ["@modelcontextprotocol/sdk"],
};

export default nextConfig;
