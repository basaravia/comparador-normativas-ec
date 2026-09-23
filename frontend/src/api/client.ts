/** Cliente HTTP mínimo. Mismo origen: la cookie de sesión `auth_session` viaja sola. */

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
  }
}

async function detalle(res: Response): Promise<string> {
  const texto = await res.text()
  try {
    const json = JSON.parse(texto)
    if (typeof json.detail === 'string') return json.detail
  } catch {
    /* no era JSON */
  }
  return texto || res.statusText
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) throw new ApiError(await detalle(res), res.status)
  return (await res.json()) as T
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export const urls = {
  stream: (runId: string) => `/api/compare/stream/${runId}`,
  run: (runId: string) => `/api/compare/runs/${runId}`,
  export: (runId: string, formato: 'excel' | 'json') => `/api/compare/runs/${runId}/export/${formato}`,
}
