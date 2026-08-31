const base = import.meta.env.VITE_API_BASE ?? "";

// The SPA sends no API key of its own. On localhost the backend runs keyless;
// for remote/LAN use it sits behind a reverse proxy that supplies auth (and, if
// desired, injects X-API-Key). This keeps any secret out of the shipped bundle.
function headers(init?: HeadersInit): HeadersInit {
  return new Headers(init);
}

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(`${base}${path}`, { headers: headers() });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json() as Promise<T>;
}

export async function apiPutJson(path: string, body: unknown): Promise<void> {
  const r = await fetch(`${base}${path}`, {
    method: "PUT",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
}

export async function apiPost(path: string): Promise<void> {
  const r = await fetch(`${base}${path}`, { method: "POST", headers: headers() });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
}

export async function apiPostJson<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${base}${path}`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json() as Promise<T>;
}

export async function apiGetText(path: string): Promise<string> {
  const r = await fetch(`${base}${path}`, { headers: headers() });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.text();
}

export async function apiPutText(path: string, body: string): Promise<void> {
  const r = await fetch(`${base}${path}`, {
    method: "PUT",
    headers: headers({ "Content-Type": "text/plain; charset=utf-8" }),
    body,
  });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
}
