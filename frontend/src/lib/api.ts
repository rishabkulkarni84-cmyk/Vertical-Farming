export class ApiError extends Error {
  status: number
  code: string
  details: unknown
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

type Opts = { method?: string; body?: unknown; form?: FormData; signal?: AbortSignal }

export async function api<T = unknown>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = { 'X-Requested-With': 'verdant' }
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  let res: Response
  try {
    res = await fetch(`/api${path}`, { method: opts.method ?? (body ? 'POST' : 'GET'), headers, body, credentials: 'include', signal: opts.signal })
  } catch {
    throw new ApiError(0, 'NETWORK', 'Cannot reach the Verdant server. Check that the backend is running.')
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  let data: any = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = null
  }
  if (!res.ok) {
    const e = data?.error
    throw new ApiError(res.status, e?.code ?? 'ERROR', e?.message ?? `Request failed (${res.status})`, e?.details)
  }
  return data as T
}

export const get = <T,>(p: string) => api<T>(p)
export const post = <T,>(p: string, body?: unknown) => api<T>(p, { method: 'POST', body: body ?? {} })
export const put = <T,>(p: string, body: unknown) => api<T>(p, { method: 'PUT', body })
export const patch = <T,>(p: string, body: unknown) => api<T>(p, { method: 'PATCH', body })
export const del = <T,>(p: string) => api<T>(p, { method: 'DELETE' })

/** Download a file served by an authenticated endpoint. */
export async function download(path: string, filename: string) {
  const res = await fetch(`/api${path}`, { credentials: 'include' })
  if (!res.ok) throw new ApiError(res.status, 'DOWNLOAD', 'Download failed')
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return 'Something went wrong'
}
