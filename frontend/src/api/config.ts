const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();

export const apiBaseUrl = (configuredApiBaseUrl || "/api/v1").replace(/\/+$/, "");
