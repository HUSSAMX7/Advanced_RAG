import { BookOpen, ChevronLeft, MessageSquare, Plus, X, PanelRightClose, Settings2 } from 'lucide-react'
import type { SessionSummary } from '../api'
import Brand from './Brand'

interface Props {
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
          <span className="workspace-dot" /> مساحة العمل المحلية{' '}
          <span className="local-badge">شخصية</span>
        </div>
        <nav className="primary-nav">
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
              <button
                key={session.id}
                disabled={props.sending}
                className={`history-item ${props.view === 'chat' && session.id === props.activeId ? 'active' : ''}`}
                onClick={() => props.onChat(session.id)}
                title={session.title}
              >
                <MessageSquare size={16} />
                <span>{session.title}</span>
              </button>
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
