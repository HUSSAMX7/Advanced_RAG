export type FileStatus =
  'untrained' | 'queued' | 'training' | 'cancelling' | 'trained' | 'failed' | 'cancelled'
export interface LibraryFile {
  id: string
  name: string
  size: number
  type: string
  status: FileStatus
  stage: string | null
  error: string | null
  warning?: string | null
  chunks: number
  created_at: string
  updated_at: string
  has_original: boolean
}
export interface Source {
  chunk_id: string
  citation: number
  metadata: {
    source?: string
    paper_path?: string
    page_num?: number
    resource_id?: string
    [key: string]: unknown
  }
}
export interface Turn {
  question: string
  answer: string
  sources: Source[]
}
export interface Session {
  session_id: string
  turns: Turn[]
}
export interface SessionSummary {
  id: string
  title: string
  turns: number
  updated_at: number
}
export interface SourceDetail {
  available: boolean
  has_original: boolean
  text: string | null
  file_id?: string
  metadata?: Source['metadata']
  images?: SourceImage[]
}
export interface SourceImage {
  id: string
  kind: 'figure' | 'page'
  page_num: number
  url: string
}
export interface Health {
  status: string
  max_upload_bytes: number
  doc_available: boolean
}

export interface AppSettings {
  pdf_provider: 'llamaparse' | 'lightonocr'
  agent_model: string
  embedding_model: string
  rerank_model: string
  lightonocr_model: string
  openai_key_configured: boolean
  llamaparse_key_configured: boolean
  embedding_locked: boolean
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      ...(typeof init?.body === 'string' ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    const detail = data?.detail
    throw new Error(typeof detail === 'string' ? detail : 'تعذر إكمال الطلب. حاول مرة أخرى.')
  }
  return response.status === 204 ? (undefined as T) : (response.json() as Promise<T>)
}

export const busyStatus = (status: FileStatus) =>
  ['queued', 'training', 'cancelling'].includes(status)
export function formatSize(bytes: number) {
  if (!bytes) return 'ملف سابق'
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`
}
