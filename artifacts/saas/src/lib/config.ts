/**
 * config.ts — SaaS Platform Configuration
 *
 * Single source of truth for all URLs and environment flags.
 * The BASE_URL is injected by Vite at build time (from artifact.toml's BASE_PATH).
 * SAAS_API_BASE is the prefix for all calls to the backend SaaS router.
 */

/**
 * The base path this app is mounted at (e.g. "/saas/").
 * Used by Wouter as the router base so in-app links stay under /saas/.
 */
export const BASE_URL: string = import.meta.env.BASE_URL ?? "/saas/";

/**
 * The root URL for all SaaS backend API calls.
 * All fetch() calls in this app should use this constant as their prefix
 * so the request correctly hits the FastAPI saas_router.
 */
export const SAAS_API_BASE: string = "/saas-api";

/**
 * Helper — builds a full API URL from a path fragment.
 * Usage: apiUrl("/health") → "/saas-api/health"
 */
export function apiUrl(path: string): string {
  return `${SAAS_API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
}
