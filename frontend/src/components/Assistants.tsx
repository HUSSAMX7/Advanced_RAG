import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUpLeft, BookOpen, Bot, Loader2, MessageSquare, Pencil, Plus, RefreshCw, Settings2, Trash2, X } from 'lucide-react'
import { api, type Assistant } from '../api'
import Brand from './Brand'
import Settings from './Settings'

export default function Assistants({ settings = false }: { settings?: boolean }) {
  const [assistants, setAssistants] = useState<Assistant[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<Assistant | null>(null)
  const [deleting, setDeleting] = useState<Assistant | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [instructions, setInstructions] = useState('')
  const [busy, setBusy] = useState(false)
  const [dialogError, setDialogError] = useState('')
  const [saved, setSaved] = useState(false)
  const editor = useRef<HTMLDialogElement>(null)
  const confirmation = useRef<HTMLDialogElement>(null)
  const nameInput = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setAssistants(await api<Assistant[]>('/assistants'))
    } catch (error) {
      setError(error instanceof Error ? error.message : 'تعذر تحميل المساعدين.')
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  function edit(assistant: Assistant | null) {
    setEditing(assistant)
    setName(assistant?.name ?? '')
    setDescription(assistant?.description ?? '')
    setInstructions(assistant?.instructions ?? '')
    setDialogError('')
    editor.current?.showModal()
    nameInput.current?.focus()
  }

  async function save() {
    if (busy || !name.trim()) return
    setBusy(true)
    setDialogError('')
    try {
      const result = await api<Assistant>(editing ? `/assistants/${editing.id}` : '/assistants', {
        method: editing ? 'PUT' : 'POST',
        body: JSON.stringify({ name: name.trim(), description: description.trim(), instructions: instructions.trim() }),
      })
      setAssistants((previous) => editing
        ? previous.map((item) => item.id === result.id ? result : item)
        : [...previous, result])
      editor.current?.close()
    } catch (error) {
      setDialogError(error instanceof Error ? error.message : 'تعذر حفظ المساعد.')
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!deleting || busy) return
    setBusy(true)
    setDialogError('')
    try {
      await api(`/assistants/${deleting.id}`, { method: 'DELETE' })
      setAssistants((previous) => previous.filter((item) => item.id !== deleting.id))
      confirmation.current?.close()
      setDeleting(null)
    } catch (error) {
      setDialogError(error instanceof Error ? error.message : 'تعذر حذف المساعد.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="assistants-shell">
      <header className="assistants-header">
        <a className="brand" href="#assistants" aria-label="مدار — المساعدون">
          <Brand /><div><strong>مدار</strong><span>مساحة المعرفة</span></div>
        </a>
        <nav aria-label="التنقل الرئيسي">
          {settings ? <a className="button secondary" href="#assistants"><Bot size={17} /> المساعدون</a>
            : <a className="button secondary" href="#settings"><Settings2 size={17} /> الإعدادات العامة</a>}
          <span className="local-badge">مساحتك المحلية</span>
        </nav>
      </header>
      {settings ? <>
        {saved && <p className="assistant-saved" role="status">تم حفظ الإعدادات لجميع المساعدين.</p>}
        <Settings busy={false} onSaved={() => setSaved(true)} />
      </> : <main className="assistants-page">
        <div className="assistants-heading">
          <div>
            <span className="eyebrow">لكل معرفة، مساعدها</span>
            <h1>مساعدوك<span className="heading-dot">.</span></h1>
            <p>مساحات مستقلة لملفاتك ومحادثاتك. اختر مساعدًا وابدأ من حيث توقفت.</p>
          </div>
          <button className="button primary" disabled={loading || !!error} onClick={() => edit(null)}><Plus size={18} /> مساعد جديد</button>
        </div>
        {error ? <div className="assistant-error" role="alert"><p>{error}</p><button className="button secondary" onClick={() => void refresh()}><RefreshCw size={16} /> إعادة المحاولة</button></div>
          : loading ? <div className="settings-loading" role="status"><Loader2 className="spin" /> جارٍ تحميل المساعدين…</div>
          : assistants.length ? <>
            <div className="assistants-count">{assistants.length.toLocaleString('ar-SA')} مساعد في مساحتك</div>
            <div className="assistants-grid">
              {assistants.map((assistant) => <article className="assistant-card" key={assistant.id}>
                <div className="assistant-card-top">
                  <span className="assistant-avatar"><Bot size={25} /></span>
                  <div className="assistant-card-actions">
                    <button className="icon-button" aria-label={`تعديل ${assistant.name}`} onClick={() => edit(assistant)}><Pencil size={16} /></button>
                    <button className="icon-button" aria-label={`حذف ${assistant.name}`} onClick={() => {
                      setDeleting(assistant); setDialogError(''); confirmation.current?.showModal()
                    }}><Trash2 size={16} /></button>
                  </div>
                </div>
                <a className="assistant-card-link" href={`#assistant/${assistant.id}/chat`} aria-label={`فتح ${assistant.name}`}>
                  <h2 dir="auto">{assistant.name}</h2>
                  <p dir="auto">{assistant.description || 'معرفة من ملفاتك، وإجابات مرتبطة بمصادرك.'}</p>
                  <div className="assistant-card-stats">
                    <span><BookOpen size={15} /> {assistant.files} ملفات</span>
                    <span><MessageSquare size={15} /> {assistant.conversations} محادثات</span>
                  </div>
                  <div className="assistant-card-footer"><span>{assistant.trained ? `${assistant.trained} ملفات جاهزة للبحث` : 'أضف ملفاتك وابدأ'}</span><ArrowUpLeft size={19} /></div>
                </a>
              </article>)}
            </div>
          </> : <div className="assistants-empty">
            <span className="empty-assistant-icon"><Bot size={42} /></span>
            <h2>معرفتك تبدأ بمساعد</h2>
            <p>أنشئ مساعدًا لمجال أو مشروع، وأضف ملفاته في مكتبته الخاصة.</p>
            <button className="button primary" onClick={() => edit(null)}><Plus size={18} /> أنشئ مساعدك الأول</button>
            <small>مثل: الموارد البشرية، الأنظمة والسياسات، أو أبحاثك.</small>
          </div>}
      </main>}

      <dialog ref={editor} className="assistant-dialog" aria-labelledby="assistant-editor-title" onCancel={(event) => { if (busy) event.preventDefault() }}>
        <form onSubmit={(event) => { event.preventDefault(); void save() }}>
          <div className="assistant-dialog-heading"><div><span className="eyebrow">مساحة معرفة خاصة</span><h2 id="assistant-editor-title">{editing ? 'تعديل المساعد' : 'مساعد جديد'}</h2></div>
            <button type="button" className="icon-button" disabled={busy} aria-label="إغلاق" onClick={() => editor.current?.close()}><X size={20} /></button>
          </div>
          <fieldset disabled={busy}>
            <label>اسم المساعد <span className="required-label">مطلوب</span><input ref={nameInput} required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} placeholder="مثل: مساعد الموارد البشرية" dir="auto" /></label>
            <label>الوصف <span className="optional-label">اختياري</span><textarea rows={2} maxLength={500} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="وصف مختصر يظهر على كرت المساعد" dir="auto" /></label>
            <label>تعليمات الإجابة <span className="optional-label">اختياري</span><textarea rows={4} maxLength={6000} value={instructions} onChange={(event) => setInstructions(event.target.value)} placeholder="مثل: أجب بالعربية وباختصار، ونظّم التفاصيل في نقاط." dir="auto" /></label>
          </fieldset>
          {dialogError && <p className="assistant-form-error" role="alert">{dialogError}</p>}
          <div className="assistant-dialog-footer"><button type="button" className="button secondary" disabled={busy} onClick={() => editor.current?.close()}>إلغاء</button><button type="submit" className="button primary" disabled={busy || !name.trim()}>{busy && <Loader2 size={16} className="spin" />}{editing ? 'حفظ التعديلات' : 'إنشاء المساعد'}</button></div>
        </form>
      </dialog>
      <dialog ref={confirmation} className="assistant-dialog" aria-labelledby="assistant-delete-title" onCancel={(event) => { if (busy) event.preventDefault() }}>
        <div className="assistant-dialog-heading"><h2 id="assistant-delete-title">حذف المساعد؟</h2><button className="icon-button" disabled={busy} aria-label="إغلاق" onClick={() => confirmation.current?.close()}><X size={20} /></button></div>
        <p className="assistant-delete-copy">سيُحذف «{deleting?.name}» نهائيًا مع جميع ملفاته وفهرستها ومحادثاته. لا يمكن التراجع عن الحذف.</p>
        {dialogError && <p className="assistant-form-error" role="alert">{dialogError}</p>}
        <div className="assistant-dialog-footer"><button className="button secondary" disabled={busy} onClick={() => confirmation.current?.close()}>إلغاء</button><button className="button danger" disabled={busy} onClick={() => void remove()}>{busy ? <Loader2 className="spin" size={16} /> : <Trash2 size={16} />} حذف المساعد وبياناته</button></div>
      </dialog>
    </div>
  )
}
