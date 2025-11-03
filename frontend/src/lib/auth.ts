export async function browserRemember(API_BASE: string, username: string, host?: string) {
  if (!username.trim()) return;
  await fetch(`${API_BASE}/browser/hello/`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username,
      host: host || window.navigator.platform || "",
    }),
  });
}