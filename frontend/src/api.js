// Leave VITE_API_URL unset in local dev to route through the Vite proxy (vite.config.js).
const BASE_URL = import.meta.env.VITE_API_URL || "";

export async function fetchDashboard() {
  const res = await fetch(`${BASE_URL}/api/dashboard`);
  if (!res.ok) throw new Error(`Dashboard fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchLogs() {
  const res = await fetch(`${BASE_URL}/logs`);
  if (!res.ok) throw new Error(`Logs fetch failed: ${res.status}`);
  return res.json();
}

export async function searchLogs(query, serviceId, limit = 10) {
  const params = new URLSearchParams({ query, limit: String(limit) });
  if (serviceId) params.set("service_id", serviceId);
  const res = await fetch(`${BASE_URL}/search?${params}`);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    const msg =
      detail.detail?.[0]?.msg ||
      (typeof detail.detail === "string" ? detail.detail : null) ||
      `Search failed: ${res.status}`;
    throw new Error(msg);
  }
  const data = await res.json();
  return data.results || [];
}

export async function explainError(errorMessage, serviceId = "") {
  const body = { error_message: errorMessage };
  if (serviceId) body.service_id = serviceId;
  const res = await fetch(`${BASE_URL}/explain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `Explain failed: ${res.status}`);
  }
  return res.json();
}
