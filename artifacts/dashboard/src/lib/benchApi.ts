function messageFromBody(body: string) {
  if (!body.trim()) return "The server returned an empty response body.";
  try {
    const parsed: unknown = JSON.parse(body);
    if (typeof parsed === "string") return parsed;
    if (parsed && typeof parsed === "object") {
      const record = parsed as Record<string, unknown>;
      const detail = record.detail ?? record.message ?? record.error;
      if (typeof detail === "string") return detail;
      if (detail && typeof detail === "object") {
        const nested = detail as Record<string, unknown>;
        if (typeof nested.message === "string") return nested.message;
      }
      return JSON.stringify(parsed);
    }
    return String(parsed);
  } catch {
    const readable = body
      .replace(/<script[\s\S]*?<\/script>/gi, " ")
      .replace(/<style[\s\S]*?<\/style>/gi, " ")
      .replace(/<[^>]+>/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    return (readable || body.trim()).slice(0, 700);
  }
}

export async function parseCatalogResponse<T>(response: Response): Promise<T> {
  const body = await response.text();
  const message = messageFromBody(body);
  if (!response.ok) {
    const statusText = response.statusText.trim();
    throw new Error(
      `HTTP ${response.status}${statusText ? ` ${statusText}` : ""}: ${message}`,
    );
  }
  if (!body.trim()) {
    throw new Error(`HTTP ${response.status}: ${message}`);
  }
  try {
    return JSON.parse(body) as T;
  } catch {
    throw new Error(
      `HTTP ${response.status}: Response was not valid JSON. ${message}`,
    );
  }
}