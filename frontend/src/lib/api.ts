/** Cliente HTTP mínimo para a API do Pandora Architect.

 * Todos os erros da API saem como `{"detail": string, "code": string}` —
 * esse cliente os converte em `ApiError` para os handlers de toast.
 */

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  /** `detail` do corpo de erro da API (FastAPI/HTTPException). */
  readonly detail: string

  constructor(status: number, code: string, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }
}

async function parseError(response: Response): Promise<ApiError> {
  let detail = `Erro HTTP ${response.status}`
  let code = `http_${response.status}`
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object') {
      const record = body as Record<string, unknown>
      if (typeof record.detail === 'string') detail = record.detail
      if (typeof record.code === 'string') code = record.code
    }
  } catch {
    // corpo não-JSON: mantém a mensagem genérica
  }
  return new ApiError(response.status, code, detail)
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal, headers: { Accept: 'application/json' } })
  if (!response.ok) throw await parseError(response)
  return (await response.json()) as T
}

export async function apiSend<T>(
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      Accept: 'application/json',
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) throw await parseError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** Mensagem legível para toasts: prioriza `detail` da API. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.detail
  if (error instanceof Error) return error.message
  return 'Erro inesperado.'
}
