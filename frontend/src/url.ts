// Whitelist http(s) URLs for use in an <a href>. Device GUI URLs come from
// operator config and could otherwise be `javascript:`/`data:` (stored XSS).
export function safeHref(raw: string): string | undefined {
  if (!raw) return undefined;
  try {
    const u = new URL(raw, document.baseURI);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : undefined;
  } catch {
    return undefined;
  }
}
