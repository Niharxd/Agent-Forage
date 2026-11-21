const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();

export function resolveApiBaseUrl(configuredUrl: string | undefined, isProduction: boolean): string {
  if (isProduction) return "/api/v1";
  return (configuredUrl || "/api/v1").replace(/\/+$/, "");
}

export const apiBaseUrl = resolveApiBaseUrl(configuredApiBaseUrl, Boolean(import.meta.env.PROD));
