import { BookOpen, ChevronLeft, Loader2, MessageSquare, Plus, RefreshCw, X, PanelRightClose, Settings2, LayoutGrid } from 'lucide-react'
import type { SessionSummary } from '../api'
import Brand from './Brand'

interface Props {
  assistantName: string
  onHome: () => void
  view: 'chat' | 'library' | 'settings'
  sessions: SessionSummary[]
  activeId?: string
  open: boolean
  sending: boolean
  trained: number
  connected: boolean
  onClose: () => void
  onLibrary: () => void
  onSettings: () => void
  onNew: () => void
  onChat: (id: string) => void
  onRetryTitle: (id: string) => void
}

export default function Sidebar(props: Props) {
  return (
    <>
      {props.open && (
        <button className="sidebar-scrim" aria-label="إغلاق القائمة" onClick={props.onClose} />
      )}
      <aside className={`sidebar ${props.open ? 'open' : ''}`} aria-label="القائمة الرئيسية">
        <div className="sidebar-brand">
          <div className="brand">
            <Brand />
            <div>
              <strong>مدار</strong>
              <span>مساحة المعرفة</span>
            </div>
          </div>
          <button
            className="icon-button mobile-only"
            aria-label="إغلاق القائمة"
            onClick={props.onClose}
          >
            <X size={19} />
          </button>
          <PanelRightClose className="desktop-sidebar-icon" size={18} />
        </div>
        <div className="workspace-label">
          <span className="workspace-dot" /><strong dir="auto">{props.assistantName}</strong>
        </div>
        <nav className="primary-nav">
          <button className="nav-item" onClick={props.onHome}><LayoutGrid size={19} /><span>كل المساعدين</span><ChevronLeft size={15} /></button>
          <button
            className={`nav-item ${props.view === 'library' ? 'selected' : ''}`}
            onClick={props.onLibrary}
          >
            <BookOpen size={19} />
            <span>المكتبة</span>
            <span className="nav-count">{props.trained}</span>
          </button>
          <button
            className="new-chat-button"
            disabled={props.sending || !props.connected}
            onClick={props.onNew}
          >
            <Plus size={19} />
            <span>محادثة جديدة</span>
            <span className="new-chat-arrow">
              <ChevronLeft size={16} />
            </span>
          </button>
        </nav>
        <div className="history-label">
          المحادثات <span>{props.sessions.length}</span>
        </div>
        <div className="chat-history">
          {props.sessions.length === 0 ? (
            <p className="history-empty">محادثاتك القادمة تبدأ هنا.</p>
          ) : (
            props.sessions.map((session) => (
              <div className="history-row" key={session.id}>
              <button
                disabled={props.sending}
                className={`history-item ${props.view === 'chat' && session.id === props.activeId ? 'active' : ''}`}
                onClick={() => props.onChat(session.id)}
                title={session.title_status === 'pending' ? 'جارٍ تسمية المحادثة' : session.title}
                aria-label={session.title_status === 'pending' ? 'جارٍ تسمية المحادثة' : session.title}
                aria-busy={session.title_status === 'pending'}
              >
                {session.title_status === 'pending' ? (
                  <>
                    <Loader2 size={16} className="spin" />
                    <span className="title-skeleton" aria-hidden="true" />
                  </>
                ) : <>
                  <MessageSquare size={16} />
                  <span>{session.title}</span>
                </>}
              </button>
              {session.title_status === 'error' && (
                <button className="icon-button title-retry" aria-label="إعادة توليد عنوان المحادثة"
                  title="إعادة توليد العنوان" onClick={() => props.onRetryTitle(session.id)}>
                  <RefreshCw size={14} />
                </button>
              )}
              </div>
            ))
          )}
        </div>
        <div className="sidebar-bottom">
          <button className={`nav-item settings-nav ${props.view === 'settings' ? 'selected' : ''}`} onClick={props.onSettings}><Settings2 size={19} /><span>الإعدادات</span></button>
          <div className="library-note">
            <span className="small-orbit">✦</span>
            <div>
              <strong>معرفة من ملفاتك</strong>
              <p>إجابات مرتبطة بمصادر مكتبتك.</p>
            </div>
          </div>
          <div className="profile">
            <span className="avatar">م</span>
            <div>
              <strong>مساحتك الخاصة</strong>
              <span>
                <i className={props.connected ? 'online' : ''} />
                {props.connected ? 'متصل محليًا' : 'غير متصل'}
              </span>
            </div>
            <span className="profile-tag">محلي</span>
          </div>
        </div>
      </aside>
    </>
  )
}
