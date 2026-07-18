import type { NextConfig } from "next";

/**
 * ORION ships as a single Python container (see ../Dockerfile): the FastAPI
 * layer serves this front end as pre-built static files, so there is no Node
 * process in production. That requires a fully static export.
 *
 * ORION_UI_BASE_PATH lets the same build be mounted at the site root ("") or
 * alongside the legacy Jinja UI (e.g. "/v2") without touching any links —
 * Next rewrites its own asset URLs and <Link> hrefs from basePath.
 */
const basePath = process.env.ORION_UI_BASE_PATH ?? "";

const nextConfig: NextConfig = {
  output: "export",
  basePath,
  // Emit directory-style routes (/plan/index.html) so a plain static file
  // server resolves them without per-route rewrite rules.
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
