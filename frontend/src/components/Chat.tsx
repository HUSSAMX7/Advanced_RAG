import { useEffect, useRef, useState } from 'react'
import {
  ArrowUp,
  ArrowUpLeft,
  BookOpen,
  Check,
  Copy,
  FileText,
  Loader2,
  Sparkles,
  X,
  Download,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, type Assistant, type Session, type Source, type SourceDetail } from '../api'
import Brand from './Brand'
import ProtectedImage from './ProtectedImage'
import { downloadFile } from '../auth-client'

interface Props {
  assistant: Assistant
  session: Session | null
  sending: boolean
  pending: string | null
  trained: number
  connected: boolean
  loading: boolean
  onLibrary: () => void
  onSend: (question: string) => Promise<{ success: boolean; restoreDraft: boolean }>
}

function Sources({ sources, assistantId }: { sources: Source[]; assistantId: string }) {
  const [selected, setSelected] = useState<Source | null>(null)
  const [detail, setDetail] = useState<SourceDetail | null>(null)
  const [error, setError] = useState('')
  const [enlarged, setEnlarged] = useState<string | null>(null)
  const [failedImages, setFailedImages] = useState<string[]>([])
  const dialog = useRef<HTMLDialogElement>(null)

  async function open(source: Source) {
    setSelected(source)
    setDetail(null)
    setError('')
    setEnlarged(null)
    setFailedImages([])
    dialog.current?.showModal()
    try {
      setDetail(await api<SourceDetail>(`/assistants/${assistantId}/sources/${encodeURIComponent(source.chunk_id)}`))
    } catch {
      setError('تعذر تحميل المصدر. حاول مرة أخرى.')
    }
  }

  return (
    <>
      <div className="answer-sources">
        <span>المصادر</span>
        {sources.map((source) => (
          <button key={source.chunk_id} className="source-chip" onClick={() => void open(source)}>
            <FileText size={14} />
            <span>{source.metadata.source ?? source.metadata.paper_path ?? 'مستند'}</span>
            {source.metadata.page_num && <small>ص {source.metadata.page_num}</small>}
            <span className="source-citation">{source.citation}</span>
          </button>
        ))}
      </div>
      <dialog className="source-dialog" ref={dialog}>
        <div className="source-dialog-header">
          <div>
            <span className="eyebrow">المقطع المستخدم في الإجابة</span>
            <h2 dir="auto">
              {selected?.metadata.source ?? selected?.metadata.paper_path ?? 'المصدر'}
            </h2>
            {selected?.metadata.page_num && <small>الصفحة {selected.metadata.page_num}</small>}
          </div>
          <button
            className="icon-button"
            aria-label="إغلاق المصدر"
            onClick={() => dialog.current?.close()}
          >
            <X size={20} />
          </button>
        </div>
        {error ? (
          <p className="source-unavailable">{error}</p>
        ) : !detail ? (
          <div className="source-loading">
            <Loader2 className="spin" size={22} /> جارٍ تحميل المقطع…
          </div>
        ) : !detail.available ? (
          <p className="source-unavailable">
            هذا المصدر لم يعد موجودًا في الفهرس. قد يكون الملف محذوفًا أو أُزيلت فهرسته؛ الإجابة
            السابقة محفوظة كما كانت.
          </p>
        ) : (
          <>
            {detail.text && (
              <div className="source-excerpt" dir="auto">
                {detail.text}
              </div>
            )}
            {!!detail.images?.length && (
              <div className="source-images">
                {detail.images.map((image) => (
                  <figure key={image.id}>
                    {failedImages.includes(image.id) ? (
                      <p className="source-unavailable">تعذر تحميل صورة المصدر. أعد فتح المصدر للمحاولة مجددًا.</p>
                    ) : (
                      <button
                        className={`source-image-button ${enlarged === image.id ? 'enlarged' : ''}`}
                        onClick={() => setEnlarged(enlarged === image.id ? null : image.id)}
                        aria-label={enlarged === image.id ? 'تصغير صورة المصدر' : 'تكبير صورة المصدر'}
                        aria-expanded={enlarged === image.id}
                      >
                        <ProtectedImage
                          src={image.url}
                          onUnavailable={() => setFailedImages((current) => [...current, image.id])}
                          alt={`${image.kind === 'page' ? 'الصفحة الأصلية' : 'صورة من المصدر'} — صفحة ${image.page_num}`}
                        />
                      </button>
                    )}
                    <figcaption>
                      {image.kind === 'page'
                        ? 'الصفحة الأصلية كاملة؛ ارتباط الشكل بالنص غير محدد'
                        : 'الصورة المرتبطة بالمقطع'}
                      {' · '}صفحة {image.page_num}{' · '}
                      {enlarged === image.id ? 'اضغط للتصغير' : 'اضغط للتكبير'}
                    </figcaption>
                  </figure>
                ))}
              </div>
            )}
            {detail.has_original && (
              <a className="button secondary" href={`/api/assistants/${assistantId}/files/${detail.file_id}/download`}
                onClick={(event) => { event.preventDefault(); void downloadFile(event.currentTarget.href,
                  selected?.metadata.source ?? 'document').catch((reason) => setError(reason.message)) }}>
                <Download size={17} /> تنزيل الملف الأصلي
              </a>
            )}
          </>
        )}
      </dialog>
    </>
  )
}

function Answer({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }
  return (
    <>
      <div className="markdown-answer">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </div>
      <button className="copy-answer" onClick={() => void copy()} aria-label="نسخ الإجابة">
        {copied ? <Check size={14} /> : <Copy size={14} />}
        {copied ? 'تم النسخ' : 'نسخ الإجابة'}
      </button>
    </>
  )
}

export default function Chat(props: Props) {
  const [draft, setDraft] = useState('')
  const input = useRef<HTMLTextAreaElement>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const turns = props.session?.turns ?? []
  const welcome = turns.length === 0 && !props.pending
  const canSend = props.connected && !props.sending && !props.loading
  useEffect(() => {
    if (!props.pending) setDraft('')
  }, [props.session?.session_id])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns.length, props.pending, props.sending])
  useEffect(() => {
    if (input.current) {
      input.current.style.height = 'auto'
      input.current.style.height = `${Math.min(input.current.scrollHeight, 160)}px`
    }
  }, [draft])

  async function send() {
    const question = draft.trim()
    if (!question || !canSend) return
    setDraft('')
    const result = await props.onSend(question)
    if (result.restoreDraft) setDraft(question)
    input.current?.focus()
  }

  return (
    <div className={`chat-page ${welcome ? 'welcome-mode' : ''}`}>
      <div className="chat-scroll">
        {props.loading ? (
          <div className="page-loading">
            <Loader2 className="spin" /> جارٍ فتح المحادثة…
          </div>
        ) : welcome ? (
          <div className="welcome">
            <div className="welcome-brand">
              <Brand large />
            </div>
            <div className="welcome-kicker">مكتبة مستقلة، معرفة أقرب</div>
            <h1>
              <span className="welcome-assistant-name" dir="auto">{props.assistant.name}</span><span>.</span>
            </h1>
            <p>
              {props.assistant.description || 'اسأل مساعدك عن الملفات، واكتشف التفاصيل مع مصادرها.'}
              <br />
              ملفات هذا المساعد ومحادثاته في مساحة خاصة به.
            </p>
            <div className="welcome-ready">
              <span className="status-dot" />
              {props.trained
                ? `${props.trained} ${props.trained === 1 ? 'ملف جاهز' : 'ملفات جاهزة'} للمحادثة`
                : 'ارفع ملفاتك ودرّبها لتصبح جاهزة للبحث'}
            </div>
            <div className="suggestion-grid">
              {[
                [
                  'لخّص الملفات',
                  'نظرة واضحة على أهم الأفكار',
                  'لخّص أهم الأفكار الواردة في ملفات هذا المساعد.',
                ],
                ['اكتشف التفاصيل', 'استخرج المعلومات المهمة بمصادرها', 'ما أهم التفاصيل والمعلومات الواردة في الملفات؟'],
                [
                  'قارن الأفكار',
                  'اربط المعلومات بين المصادر',
                  'قارن أهم الموضوعات في الملفات، ووضّح نقاط الاتفاق والاختلاف.',
                ],
              ].map(([title, description, question], index) => (
                <button
                  key={title}
                  className="suggestion"
                  onClick={() => {
                    setDraft(question)
                    input.current?.focus()
                  }}
                >
                  <span className={`suggestion-icon suggestion-${index}`}>
                    {index === 0 ? (
                      <FileText size={20} />
                    ) : index === 1 ? (
                      <Sparkles size={20} />
                    ) : (
                      <BookOpen size={20} />
                    )}
                  </span>
                  <strong>{title}</strong>
                  <span>{description}</span>
                  <ArrowUpLeft className="suggestion-arrow" size={17} />
                </button>
              ))}
            </div>
            {!props.trained && (
              <button className="welcome-library-link" onClick={props.onLibrary}>
                أضف ملفاتك للمحادثة من المكتبة <ArrowUpLeft size={16} />
              </button>
            )}
          </div>
        ) : (
          <div className="messages">
            {turns.map((turn, index) => (
              <div className="turn" key={index}>
                <div className="user-message">
                  <span className="user-label">أنت</span>
                  <p dir="auto">{turn.question}</p>
                </div>
                <div className="assistant-message">
                  <div className="assistant-label">
                    <Brand />
                    <strong dir="auto">{props.assistant.name}</strong>
                    {!!turn.sources.length && <span>من مكتبتك</span>}
                  </div>
                  <Answer text={turn.answer} />
                  {!!turn.sources.length && <Sources sources={turn.sources} assistantId={props.assistant.id} />}
                </div>
              </div>
            ))}
            {props.pending && (
              <div className="turn">
                <div className="user-message">
                  <span className="user-label">أنت</span>
                  <p dir="auto">{props.pending}</p>
                </div>
                <div className="assistant-message">
                  <div className="assistant-label">
                    <Brand />
                    <strong dir="auto">{props.assistant.name}</strong>
                  </div>
                  <div className="thinking" role="status">
                    <span />
                    <span />
                    <span />
                    <small>أجهّز الإجابة…</small>
                  </div>
                </div>
              </div>
            )}
            <div ref={bottom} />
          </div>
        )}
      </div>
      <div className="composer-area">
        <div className={`composer ${!canSend ? 'disabled' : ''}`}>
          <textarea
            ref={input}
            value={draft}
            disabled={!canSend}
            rows={1}
            aria-label="رسالتك"
            placeholder={
              props.sending
                ? 'جارٍ تجهيز إجابتك…'
                : !props.connected
                  ? 'الاتصال بالخادم غير متوفر'
                  : 'اسأل مساعدك عن ملفاته…'
            }
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault()
                void send()
              }
            }}
          />
          <div className="composer-tools">
            <span className="composer-context">
              <BookOpen size={14} />
              {props.trained ? 'البحث في ملفات هذا المساعد' : 'لا توجد ملفات مدرّبة بعد'}
            </span>
            <button
              className="send-button"
              disabled={!canSend || !draft.trim()}
              aria-label="إرسال الرسالة"
              onClick={() => void send()}
            >
              {props.sending ? <Loader2 size={20} className="spin" /> : <ArrowUp size={21} />}
            </button>
          </div>
        </div>
        <p className="composer-note">
          يبحث مساعدك في ملفاته للإجابة عن أسئلتك. راجع الإجابات والمصادر للتأكد.
        </p>
      </div>
    </div>
  )
}
