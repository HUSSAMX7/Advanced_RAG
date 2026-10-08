import { useCallback, useEffect, useRef, useState } from 'react'
import {
  BookOpen,
  ChevronLeft,
  CheckCircle2,
  Loader2,
  Menu,
  MessageSquare,
  RefreshCw,
  X,
  AlertCircle,
  Settings2,
} from 'lucide-react'
import {
  api,
  busyStatus,
  type Health,
  type LibraryFile,
  type Session,
  type SessionSummary,
  type Turn,
} from './api'
import Sidebar from './components/Sidebar'
import Library from './components/Library'
import Chat from './components/Chat'
import Settings from './components/Settings'

export default function App() {
  const [view, setView] = useState<'chat' | 'library' | 'settings'>('chat')
  const [files, setFiles] = useState<LibraryFile[]>([])
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [session, setSession] = useState<Session | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sending, setSending] = useState(false)
  const [loadingChat, setLoadingChat] = useState(false)
  const [pending, setPending] = useState<string | null>(null)
  const [pendingSession, setPendingSession] = useState<string | null>(null)
  const [uploading, setUploading] = useState<string | null>(null)
  const [actions, setActions] = useState<Set<string>>(new Set())
  const [toast, setToast] = useState<{ message: string; error: boolean } | null>(null)
  const sendLock = useRef(false)
  const routeTicket = useRef(0)
  const currentSession = useRef<Session | null>(null)
  const requestedSession = useRef<string | null>(null)
  const connectedOnce = useRef(false)
  const trained = files.filter((file) => file.status === 'trained').length
  useEffect(() => {
    currentSession.current = session
  }, [session])

  const notify = useCallback((message: string, error = false) => setToast({ message, error }), [])
  const refresh = useCallback(
    async (silent = false) => {
      try {
        const [newFiles, newSessions, newHealth] = await Promise.all([
          api<LibraryFile[]>('/files'),
          api<SessionSummary[]>('/sessions'),
          api<Health>('/health'),
        ])
        setFiles(newFiles)
        setSessions(newSessions)
        setHealth(newHealth)
        connectedOnce.current = true
      } catch {
        setHealth(null)
        if (!silent) notify('تعذر الاتصال بالخادم. تأكد من تشغيل التطبيق ثم أعد المحاولة.', true)
      }
    },
    [notify],
  )

  useEffect(() => {
    void refresh()
  }, [refresh])
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 5500)
    return () => clearTimeout(timer)
  }, [toast])
  useEffect(() => {
    const timer = setInterval(
      () => {
        void refresh(true)
      },
      files.some((file) => busyStatus(file.status)) ? 2000 : 10000,
    )
    return () => clearInterval(timer)
  }, [files, refresh])
  useEffect(() => {
    async function route() {
      const ticket = ++routeTicket.current
      setSidebarOpen(false)
      if (window.location.hash === '#library') {
        setView('library')
        return
      }
      if (window.location.hash === '#settings') {
        setView('settings')
        return
      }
      setView('chat')
      const id = window.location.hash.startsWith('#chat/') ? window.location.hash.slice(6) : null
      requestedSession.current = id
      if (!id) {
        setSession(null)
        setLoadingChat(false)
        return
      }
      if (currentSession.current?.session_id === id) {
        setSession(currentSession.current)
        setLoadingChat(false)
        return
      }
      setLoadingChat(true)
      try {
        const loaded = await api<Session>(`/sessions/${encodeURIComponent(id)}`)
        if (ticket === routeTicket.current) {
          currentSession.current = loaded
          setSession(loaded)
        }
      } catch (error) {
        if (ticket === routeTicket.current) {
          currentSession.current = null
          setSession(null)
          notify(error instanceof Error ? error.message : 'تعذر فتح المحادثة.', true)
        }
      } finally {
        if (ticket === routeTicket.current) setLoadingChat(false)
      }
    }
    void route()
    window.addEventListener('hashchange', route)
    return () => window.removeEventListener('hashchange', route)
  }, [notify])

  function library() {
    window.location.hash = 'library'
    setSidebarOpen(false)
  }
  function chat(id?: string) {
    window.location.hash = id ? `chat/${id}` : 'chat'
    setSidebarOpen(false)
  }
  async function newChat() {
    if (sendLock.current) return
    sendLock.current = true
    setSending(true)
    try {
      const created = await api<Session>('/sessions', { method: 'POST' })
      currentSession.current = created
      setSession(created)
      chat(created.session_id)
      await refresh(true)
    } catch (error) {
      notify(error instanceof Error ? error.message : 'تعذر إنشاء المحادثة.', true)
    } finally {
      sendLock.current = false
      setSending(false)
    }
  }

  async function send(question: string): Promise<{ success: boolean; restoreDraft: boolean }> {
    if (sendLock.current) return { success: false, restoreDraft: true }
    const initialRoute = window.location.hash
    let originId = session?.session_id ?? null
    sendLock.current = true
    setSending(true)
    setPending(question)
    setPendingSession(originId)
    try {
      let current = session
      if (!current) {
        current = await api<Session>('/sessions', { method: 'POST' })
        originId = current.session_id
        setPendingSession(originId)
        if (window.location.hash === initialRoute) {
          requestedSession.current = originId
          currentSession.current = current
          setSession(current)
          chat(current.session_id)
        }
      }
      const result = await api<{ answer: string; sources: Turn['sources']; session_id: string }>(
        `/sessions/${current.session_id}/messages`,
        { method: 'POST', body: JSON.stringify({ question }) },
      )
      const updated = {
        session_id: current.session_id,
        turns: [...current.turns, { question, answer: result.answer, sources: result.sources }],
      }
      if (requestedSession.current === current.session_id) {
        currentSession.current = updated
        setSession(updated)
      }
      await refresh(true)
      return { success: true, restoreDraft: false }
    } catch (error) {
      notify(error instanceof Error ? error.message : 'تعذر إرسال الرسالة.', true)
      return { success: false, restoreDraft: requestedSession.current === originId }
    } finally {
      setSending(false)
      setPending(null)
      setPendingSession(null)
      sendLock.current = false
    }
  }

  async function upload(selected: File[]) {
    if (uploading || !selected.length) return
    let count = 0
    for (const file of selected) {
      if (!/\.(pdf|docx|doc|txt)$/i.test(file.name)) {
        notify(`صيغة ${file.name} غير مدعومة.`, true)
        continue
      }
      if (file.size > (health?.max_upload_bytes ?? 50 * 1024 * 1024)) {
        notify(`${file.name} أكبر من الحد المسموح.`, true)
        continue
      }
      setUploading(file.name)
      const body = new FormData()
      body.append('file', file)
      try {
        await api<LibraryFile>('/files', { method: 'POST', body })
        count++
      } catch (error) {
        notify(`${file.name}: ${error instanceof Error ? error.message : 'تعذر الرفع.'}`, true)
      }
    }
    setUploading(null)
    await refresh(true)
    if (count)
      notify(`تم رفع ${count === 1 ? 'الملف' : `${count} ملفات`}. اضغط «تدريب» لتجهيزها للمحادثة.`)
  }

  async function action(file: LibraryFile, operation: 'train' | 'cancel' | 'unindex' | 'delete') {
    setActions((current) => new Set(current).add(file.id))
    try {
      await api(`/files/${file.id}${operation === 'delete' ? '' : `/${operation}`}`, {
        method: operation === 'delete' ? 'DELETE' : 'POST',
      })
      if (operation === 'train') notify('بدأ تجهيز الملف. يمكنك متابعة حالته من المكتبة.')
      else
        notify(
          operation === 'delete'
            ? 'تم حذف الملف ومقاطعه من المكتبة.'
            : operation === 'unindex'
              ? 'تمت إزالة الفهرسة. الملف الأصلي محفوظ.'
              : 'انتهى طلب إيقاف التدريب؛ راجع حالة الملف.',
        )
      await refresh(true)
    } catch (error) {
      notify(error instanceof Error ? error.message : 'تعذر إكمال العملية.', true)
    } finally {
      setActions((current) => {
        const next = new Set(current)
        next.delete(file.id)
        return next
      })
    }
  }

  // Notify completion only for jobs this page has already observed running.
  const previousFiles = useRef<LibraryFile[]>([])
  useEffect(() => {
    for (const file of files) {
      const previous = previousFiles.current.find((row) => row.id === file.id)
      if (previous && busyStatus(previous.status) && file.status === 'trained')
        notify(`تم تدريب ${file.name} بنجاح.`)
      if (previous && busyStatus(previous.status) && file.status === 'failed')
        notify(`فشل تدريب ${file.name}: ${file.error}`, true)
    }
    previousFiles.current = files
  }, [files, notify])

  return (
    <div className="app-shell">
      <Sidebar
        view={view}
        sessions={sessions}
        activeId={session?.session_id}
        open={sidebarOpen}
        sending={sending}
        trained={trained}
        connected={!!health}
        onClose={() => setSidebarOpen(false)}
        onLibrary={library}
        onSettings={() => { window.location.hash = 'settings'; setSidebarOpen(false) }}
        onNew={() => void newChat()}
        onChat={chat}
      />
      <main className="main-panel">
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              className="icon-button mobile-only"
              aria-label="فتح القائمة"
              onClick={() => setSidebarOpen(true)}
            >
              <Menu size={21} />
            </button>
            <span>مساحة العمل</span>
            <ChevronLeft size={13} />
            <strong>
              {view === 'settings' ? <><Settings2 size={16} /> الإعدادات</> : view === 'library' ? (
                <>
                  <BookOpen size={16} /> المكتبة
                </>
              ) : (
                <>
                  <MessageSquare size={16} />{' '}
                  {session?.turns[0]?.question.slice(0, 40) ?? 'محادثة جديدة'}
                </>
              )}
            </strong>
          </div>
          <span className="topbar-status">
            <span className={health ? 'online' : 'offline'} />
            {health ? 'مكتبتك المحلية' : 'جارٍ التحقق من الاتصال'}
          </span>
        </header>
        {!health && (
          <div className="connection-banner">
            <AlertCircle size={17} />
            <span>
              {connectedOnce.current
                ? 'انقطع الاتصال بالخادم. ملفاتك ومحادثاتك المحفوظة تبقى محفوظة.'
                : 'الاتصال بالخادم غير متوفر حاليًا.'}
            </span>
            <button onClick={() => void refresh()}>
              <RefreshCw size={14} /> إعادة المحاولة
            </button>
          </div>
        )}
        {view === 'settings' ? (
          <Settings busy={sending || files.some((file) => busyStatus(file.status))} onSaved={() => notify('تم حفظ الإعدادات. ستُستخدم في العمليات القادمة.')} />
        ) : view === 'library' ? (
          <Library
            files={files}
            health={health}
            uploading={uploading}
            actions={actions}
            onUpload={(selected) => void upload(selected)}
            onAction={(file, operation) => void action(file, operation)}
            onChat={() => chat(session?.session_id)}
          />
        ) : (
          <Chat
            session={session}
            sending={sending}
            pending={(session?.session_id ?? null) === pendingSession ? pending : null}
            trained={trained}
            connected={!!health}
            loading={loadingChat}
            onLibrary={library}
            onSend={send}
          />
        )}
      </main>
      {toast && (
        <div
          className={`toast ${toast.error ? 'error' : ''}`}
          role={toast.error ? 'alert' : 'status'}
        >
          {toast.error ? <AlertCircle size={19} /> : <CheckCircle2 size={19} />}
          <span>{toast.message}</span>
          <button aria-label="إغلاق الإشعار" onClick={() => setToast(null)}>
            <X size={16} />
          </button>
        </div>
      )}
      {uploading && view !== 'library' && (
        <div className="background-upload">
          <Loader2 size={16} className="spin" /> جارٍ رفع {uploading}
        </div>
      )}
    </div>
  )
}
