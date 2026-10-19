import { createClient, type SupabaseClient } from '@supabase/supabase-js'

export interface AuthConfig {
  enabled: boolean
  configured?: boolean
  supabase_url?: string
  publishable_key?: string
}
export interface GuestIdentity {
  kind: 'guest'
  id: string
  renew_at: number
  expires_at: number
  server_time: number
}
export interface AccountIdentity { kind: 'account'; id: string; email: string }
export type Identity = GuestIdentity | AccountIdentity

export function emailSignInError(error: unknown): string {
  const details = typeof error === 'object' && error !== null ? error : {}
  const code = 'code' in details ? details.code : undefined
  const status = 'status' in details ? details.status : undefined
  if (code === 'over_email_send_rate_limit') {
    return 'وصلنا للحد المؤقت لإرسال رسائل التحقق. انتظر قبل طلب رسالة جديدة، أو استخدم آخر رسالة وصلتك.'
  }
  if (code === 'over_request_rate_limit' || status === 429) {
    return 'طلبات التحقق كثيرة حاليًا. انتظر قليلًا قبل المحاولة مرة أخرى.'
  }
  if (code === 'email_address_invalid') {
    return 'عنوان الإيميل غير مقبول. تحقق من العنوان وحاول مرة أخرى.'
  }
  if (code === 'email_address_not_authorized') {
    return 'إرسال التحقق لهذا الإيميل غير متاح حاليًا. يمكنك المتابعة كضيف.'
  }
  return 'تعذر إرسال رسالة التحقق الآن. حاول لاحقًا أو تابع كضيف.'
}

export const GUEST_TOKEN_KEY = 'madar.guest-session'
export const AUTH_EXPIRED_EVENT = 'madar:session-expired'
let currentHeaders: Record<string, string> = {}
let credentialVersion = 0
let client: SupabaseClient | null = null
let initialization: Promise<{ config: AuthConfig; client: SupabaseClient | null }> | null = null

export function setCredentials(kind: 'guest' | 'account' | 'local', token = '') {
  credentialVersion += 1
  currentHeaders = kind === 'guest' ? { 'X-Guest-Token': token }
    : kind === 'account' ? { Authorization: `Bearer ${token}` } : {}
}

export async function authFetch(url: string, init?: RequestInit) {
  const version = credentialVersion
  const headers = new Headers(currentHeaders)
  new Headers(init?.headers).forEach((value, key) => headers.set(key, value))
  const response = await fetch(url, { ...init, headers, cache: 'no-store' })
  if (response.status === 401 && version === credentialVersion) window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
  return response
}

export async function authJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authFetch(`/api/auth${path}`, init)
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || 'تعذر إكمال الطلب. حاول مرة أخرى.')
  return data as T
}

export function initializeAuth() {
  initialization ??= (async () => {
    const response = await fetch('/api/auth/config', { cache: 'no-store' })
    if (!response.ok) throw new Error('تعذر الاتصال بالخادم. حاول مرة أخرى.')
    const config = await response.json() as AuthConfig
    if (config.enabled && config.configured && config.supabase_url && config.publishable_key) {
      client = createClient(config.supabase_url, config.publishable_key, {
        auth: { flowType: 'pkce', detectSessionInUrl: true, persistSession: true, autoRefreshToken: true },
      })
    }
    return { config, client }
  })()
  return initialization
}

export async function endGuest(token: string) {
  if (!token) return
  const response = await fetch('/api/auth/guest/end', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }), keepalive: true,
  })
  if (!response.ok) throw new Error('تعذر إنهاء جلسة الضيف. حاول مرة أخرى.')
}

export async function downloadFile(path: string, filename: string) {
  const response = await authFetch(path)
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    throw new Error(data?.detail || 'تعذر تنزيل الملف.')
  }
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
