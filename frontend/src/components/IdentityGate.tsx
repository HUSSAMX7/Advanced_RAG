import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Loader2, LogIn, LogOut, Mail, Clock3, RefreshCw } from 'lucide-react'
import type { SupabaseClient } from '@supabase/supabase-js'
import {
  AUTH_EXPIRED_EVENT, GUEST_TOKEN_KEY, authJson, endGuest, initializeAuth,
  setCredentials, type AuthConfig, type GuestIdentity, type Identity,
} from '../auth-client'

export default function IdentityGate({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AuthConfig | null>(null)
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [starting, setStarting] = useState(true)
  const [login, setLogin] = useState(false)
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [now, setNow] = useState(Date.now() / 1000)
  const [offset, setOffset] = useState(0)
  const client = useRef<SupabaseClient | null>(null)
  const guestToken = useRef('')
  const generation = useRef(0)
  const expired = useRef(false)
  const loginDialog = useRef<HTMLDialogElement>(null)
  const renewalDialog = useRef<HTMLDialogElement>(null)
  const renewal = identity?.kind === 'guest' && now + offset >= identity.renew_at

  useEffect(() => {
    if (login && identity && !renewal) loginDialog.current?.showModal()
    else loginDialog.current?.close()
    if (renewal) renewalDialog.current?.showModal()
    else renewalDialog.current?.close()
  }, [login, identity, renewal])

  const acceptGuest = useCallback((guest: GuestIdentity) => {
    setOffset(guest.server_time - Date.now() / 1000)
    setIdentity(guest)
    expired.current = false
  }, [])

  const startGuest = useCallback(async () => {
    setStarting(true)
    setError('')
    try {
      const guest = await authJson<GuestIdentity & { token: string }>('/guest', { method: 'POST' })
      guestToken.current = guest.token
      sessionStorage.setItem(GUEST_TOKEN_KEY, guest.token)
      setCredentials('guest', guest.token)
      acceptGuest(guest)
      window.location.hash = '#assistants'
    } catch (error) {
      setError(error instanceof Error ? error.message : 'تعذر بدء الجلسة.')
    } finally { setStarting(false) }
  }, [acceptGuest])

  useEffect(() => {
    let active = true
    let subscription: { unsubscribe: () => void } | undefined
    async function setup() {
      try {
        const initialized = await initializeAuth()
        if (!active) return
        setConfig(initialized.config)
        client.current = initialized.client
        if (!initialized.config.enabled) {
          setCredentials('local')
          setStarting(false)
          return
        }
        if (initialized.client) {
          // Do not await SDK calls inside an auth-state callback (SDK holds a lock).
          subscription = initialized.client.auth.onAuthStateChange((event, session) => {
            if (!active) return
            if (event === 'SIGNED_OUT') {
              if (!guestToken.current) { setCredentials('local'); setIdentity(null) }
              return
            }
            if (!session) return
            setTimeout(() => { if (active) void useAccount(session.access_token) }, 0)
          }).data.subscription
          const { data, error } = await initialized.client.auth.getSession()
          if (error) throw error
          if (data.session) {
            await useAccount(data.session.access_token)
            return
          }
        }
        const token = sessionStorage.getItem(GUEST_TOKEN_KEY)
        const navigation = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
        if (token && navigation?.type === 'reload') {
          const response = await fetch('/api/auth/guest/resume', {
            method: 'POST', headers: { 'X-Guest-Token': token }, cache: 'no-store',
          })
          if (response.ok && active) {
            guestToken.current = token
            setCredentials('guest', token)
            acceptGuest(await response.json())
            setStarting(false)
            return
          }
        }
        // Reopened/restored tabs start fresh; no permanent guest history.
        sessionStorage.removeItem(GUEST_TOKEN_KEY)
        if (active) setStarting(false)
      } catch (error) {
        if (active) {
          setError(error instanceof Error ? error.message : 'تعذر الاتصال بالخادم.')
          setStarting(false)
        }
      }
    }
    async function useAccount(token: string) {
      const ticket = ++generation.current
      try {
        const response = await fetch('/api/auth/session', {
          headers: { Authorization: `Bearer ${token}` }, cache: 'no-store',
        })
        const account = await response.json()
        if (!response.ok) throw new Error(account.detail || 'تعذر التحقق من الدخول.')
        if (!active || ticket !== generation.current) return
        const oldGuest = guestToken.current || sessionStorage.getItem(GUEST_TOKEN_KEY) || ''
        if (oldGuest) await endGuest(oldGuest)
        if (!active || ticket !== generation.current) return
        guestToken.current = ''
        sessionStorage.removeItem(GUEST_TOKEN_KEY)
        setCredentials('account', token)
        setIdentity(account)
        expired.current = false
        setLogin(false)
        setSent(false)
        setError('')
        setStarting(false)
        // Verification callbacks and old guest assistant routes are not account routes.
        if (window.location.search || oldGuest) {
          history.replaceState(null, '', `${window.location.pathname}#assistants`)
          window.dispatchEvent(new HashChangeEvent('hashchange'))
        }
      } catch (error) {
        if (active && ticket === generation.current) {
          setError(error instanceof Error ? error.message : 'تعذر التحقق من الدخول.')
          setStarting(false)
        }
      }
    }
    void setup()
    return () => { active = false; subscription?.unsubscribe() }
  }, [acceptGuest])

  const leave = useCallback(async () => {
    generation.current += 1
    setBusy(true)
    setError('')
    try {
      if (guestToken.current) await endGuest(guestToken.current)
      else if (client.current) {
        const { error } = await client.current.auth.signOut()
        if (error) throw error
      }
      guestToken.current = ''
      sessionStorage.removeItem(GUEST_TOKEN_KEY)
      setCredentials('local')
      setIdentity(null)
      setLogin(false)
      window.location.hash = '#assistants'
    } catch (error) {
      setError(error instanceof Error ? error.message : 'تعذر إنهاء الجلسة.')
    } finally { setBusy(false) }
  }, [])

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000)
    const refreshTime = () => setNow(Date.now() / 1000)
    document.addEventListener('visibilitychange', refreshTime)
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', refreshTime) }
  }, [])

  useEffect(() => {
    const ended = () => {
      if (expired.current) return
      expired.current = true
      generation.current += 1
      const token = guestToken.current
      guestToken.current = ''
      sessionStorage.removeItem(GUEST_TOKEN_KEY)
      setCredentials('local')
      setIdentity(null)
      setLogin(false)
      setError('انتهت الجلسة. يمكنك البدء من جديد أو تسجيل الدخول.')
      if (token) void endGuest(token).catch(() => {}) // server expiry also schedules cleanup
    }
    window.addEventListener(AUTH_EXPIRED_EVENT, ended)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, ended)
  }, [])

  useEffect(() => {
    if (identity?.kind === 'guest' && now + offset >= identity.expires_at) {
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
    }
  }, [identity, now, offset])

  useEffect(() => {
    const closing = () => {
      const token = guestToken.current
      if (token) navigator.sendBeacon('/api/auth/guest/closing',
        new Blob([JSON.stringify({ token })], { type: 'application/json' }))
    }
    // The server allows a short navigation grace so a reload can resume.
    window.addEventListener('pagehide', closing)
    return () => window.removeEventListener('pagehide', closing)
  }, [])

  async function sendEmail() {
    if (!client.current || busy) return
    setBusy(true)
    setError('')
    try {
      const { error } = await client.current.auth.signInWithOtp({
        email: email.trim(), options: { emailRedirectTo: `${window.location.origin}/`, shouldCreateUser: true },
      })
      if (error) throw error
      setSent(true)
    } catch {
      setError('تعذر إرسال رسالة التحقق. تأكد من الإيميل وحاول مرة أخرى.')
    } finally { setBusy(false) }
  }

  async function renew() {
    setBusy(true)
    setError('')
    try { acceptGuest(await authJson<GuestIdentity>('/guest/renew', { method: 'POST' })) }
    catch (error) { setError(error instanceof Error ? error.message : 'تعذر تجديد الجلسة.') }
    finally { setBusy(false) }
  }

  if (config?.enabled === false) return children
  if (starting) return <div className="identity-entry" role="status"><Loader2 className="spin" /> جارٍ فتح مساحتك…</div>
  const remaining = identity?.kind === 'guest' ? Math.max(0, Math.ceil(identity.expires_at - now - offset)) : 0

  const loginForm = <form className="identity-form" onSubmit={(event) => { event.preventDefault(); void sendEmail() }}>
    <Mail size={28} /><h2>ادخل بإيميلك</h2>
    <p>نرسل لك رابط تحقق للدخول. حسابك يحفظ مساعديك وملفاتك ومحادثاتك.</p>
    {identity?.kind === 'guest' && <p className="identity-note">شغل جلسة الضيف لا ينتقل للحساب.</p>}
    <label htmlFor="login-email">الإيميل</label>
    <input id="login-email" type="email" dir="ltr" required maxLength={254} autoComplete="email" value={email} disabled={busy} onChange={(event) => { setEmail(event.target.value); setSent(false) }} />
    {sent && <p role="status">أرسلنا رسالة التحقق. افتح إيميلك واضغط رابط الدخول.</p>}
    {!config?.configured && <p role="status">تسجيل الدخول غير متاح حاليًا. يمكنك المتابعة كضيف.</p>}
    <button className="button primary" disabled={busy || !config?.configured || sent}>{busy ? <Loader2 className="spin" size={17} /> : <Mail size={17} />} إرسال رسالة التحقق</button>
  </form>

  return <>
    {identity ? <>
      <div className="identity-bar">
        <span>{identity.kind === 'guest' ? 'جلسة ضيف · شغلك مؤقت' : identity.email}</span>
        <div>{identity.kind === 'guest' && <button className="button secondary" onClick={() => { setLogin(true); setSent(false); setError('') }}><LogIn size={16} /> تسجيل الدخول</button>}
          <button className="button secondary" disabled={busy} onClick={() => void leave()}><LogOut size={16} /> {identity.kind === 'guest' ? 'إنهاء الجلسة' : 'تسجيل الخروج'}</button></div>
      </div>
      <div className="identity-content" key={`${identity.kind}:${identity.id}`}>{children}</div>
    </> : <main className="identity-entry"><div className="identity-card">
      <span className="eyebrow">مدار · مساحة المعرفة</span><h1>معرفتك تبدأ هنا.</h1>
      {loginForm}
      <button className="button secondary" disabled={busy || !config} onClick={() => void startGuest()}>المتابعة كضيف</button>
      <small>للضيف كامل الوظائف. تنتهي بياناته عند إنهاء الجلسة أو إغلاق الصفحة، ويحتاج تجديدًا كل ١٥ دقيقة.</small>
    </div></main>}
    {error && <div className="identity-error" role="alert">{error}</div>}
    {login && identity && !renewal && <dialog ref={loginDialog} className="identity-card identity-modal" aria-label="تسجيل الدخول" onCancel={() => setLogin(false)}>
      {loginForm}<button className="button secondary" onClick={() => setLogin(false)}>العودة لجلسة الضيف</button>
    </dialog>}
    {renewal && <dialog ref={renewalDialog} className="identity-card identity-modal" role="alertdialog" aria-labelledby="renew-title" onCancel={(event) => event.preventDefault()}>
      <Clock3 size={30} /><h2 id="renew-title">كملت ربع ساعة، تبي تكمّل؟</h2>
      <p>جدّد جلستك ١٥ دقيقة إضافية. إذا ما جدّدتها، تنتهي الجلسة ويُحذف شغلك.</p>
      <p className="renew-countdown" aria-live="off">متبقي {remaining} ثانية</p>
      <button className="button primary" disabled={busy} onClick={() => void renew()}><RefreshCw size={17} /> تجديد الجلسة</button>
      <button className="button secondary" disabled={busy} onClick={() => void leave()}>إنهاء الجلسة وحذف البيانات</button>
      <p>سجّل حسابًا لحفظ شغلك القادم والرجوع له لاحقًا.</p>
    </dialog>}
  </>
}
