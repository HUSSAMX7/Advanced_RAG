import { useEffect, useState } from 'react'
import { Check, Cloud, Cpu, KeyRound, Loader2, Save, Settings2, ShieldCheck, Trash2, AlertCircle } from 'lucide-react'
import { api, type AppSettings } from '../api'

interface Props {
  busy: boolean
  onSaved: () => void
}

const models = [
  ['agent_model', 'مودل المحادثة', 'يُستخدم للإجابات والأقسام وتوصيف صور PDF؛ اختر مودلًا يدعم قراءة الصور.'],
  ['embedding_model', 'مودل embeddings', 'يحوّل مقاطع ملفاتك إلى متجهات للبحث.'],
  ['rerank_model', 'مودل ترتيب النتائج', 'BGE يعمل محليًا لترتيب المقاطع الأكثر صلة بالسؤال.'],
  ['lightonocr_model', 'مودل LightOnOCR', 'يقرأ صفحات PDF على جهازك عند اختيار الاستخراج المحلي.'],
] as const

export default function Settings({ busy, onSaved }: Props) {
  const [saved, setSaved] = useState<AppSettings | null>(null)
  const [draft, setDraft] = useState<AppSettings | null>(null)
  const [keys, setKeys] = useState({ openai_api_key: '', llama_parse_api_key: '' })
  const [remove, setRemove] = useState({ openai_api_key: false, llama_parse_api_key: false })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    void api<AppSettings>('/settings').then((value) => {
      if (active) { setSaved(value); setDraft(value); setError('') }
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : 'تعذر تحميل الإعدادات.')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [attempt])

  const dirty = draft && saved && (
    draft.pdf_provider !== saved.pdf_provider || models.some(([name]) => draft[name] !== saved[name]) ||
    Object.values(keys).some(Boolean) || Object.values(remove).some(Boolean)
  )

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (!draft || saving || busy) return
    setSaving(true)
    setError('')
    const body: Record<string, string> = { pdf_provider: draft.pdf_provider }
    for (const [name] of models) body[name] = draft[name].trim()
    for (const name of ['openai_api_key', 'llama_parse_api_key'] as const) {
      if (remove[name]) body[name] = ''
      else if (keys[name].trim()) body[name] = keys[name].trim()
    }
    try {
      const value = await api<AppSettings>('/settings', { method: 'PUT', body: JSON.stringify(body) })
      setSaved(value); setDraft(value)
      setKeys({ openai_api_key: '', llama_parse_api_key: '' })
      setRemove({ openai_api_key: false, llama_parse_api_key: false })
      onSaved()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'تعذر حفظ الإعدادات.')
    } finally { setSaving(false) }
  }

  return (
    <div className="settings-page">
      <div className="settings-heading">
        <span className="eyebrow">مساحة العمل / التفضيلات</span>
        <h1>الإعدادات</h1>
        <p>اختر كيف تقرأ ملفاتك، واضبط الموديلات ومفاتيح الخدمات.</p>
      </div>
      {error && <div className="settings-error" role="alert"><AlertCircle size={18} /><span>{error}</span>
        {!draft && <button onClick={() => setAttempt((value) => value + 1)}>إعادة المحاولة</button>}
      </div>}
      {loading ? <div className="settings-loading"><Loader2 className="spin" size={20} /> جارٍ تحميل الإعدادات…</div> : draft && (
        <form onSubmit={(event) => void save(event)}>
          <fieldset disabled={saving}>
            <section className="settings-section">
              <div className="settings-section-title"><span><Cpu size={20} /></span><div><h2>استخراج ملفات PDF</h2><p>المزوّد المختار يُستخدم عند ضغط «تدريب» في المكتبة.</p></div></div>
              <div className="provider-options">
                {([
                  ['lightonocr', 'LightOnOCR محلي', 'قراءة الملف على جهازك، بدون مفتاح OCR.', Cpu],
                  ['llamaparse', 'LlamaParse API', 'قراءة الملف عبر خدمة LlamaParse باستخدام مفتاحك.', Cloud],
                ] as const).map(([value, title, description, Icon]) => (
                  <label className={`provider-card ${draft.pdf_provider === value ? 'chosen' : ''}`} key={value}>
                    <input type="radio" name="pdf-provider" value={value} checked={draft.pdf_provider === value} onChange={() => setDraft({ ...draft, pdf_provider: value })} />
                    <div className="provider-card-top"><Icon size={22} /><span className="provider-radio">{draft.pdf_provider === value && <Check size={12} />}</span></div>
                    <strong>{title}</strong><p>{description}</p>
                  </label>
                ))}
              </div>
              {draft.pdf_provider === 'lightonocr' && <p className="settings-hint"><Cpu size={16} /><span>يبدأ تلقائيًا عند التدريب ويتوقف بعد استخراج الملف. يُحمَّل المودل مرة واحدة؛ التشغيل على المعالج قد يأخذ وقتًا، ودقة العربية قد تختلف.</span></p>}
            </section>
            <section className="settings-section">
              <div className="settings-section-title"><span><KeyRound size={20} /></span><div><h2>مفاتيح الخدمات</h2><p>الشات والـembeddings يستخدمان OpenAI حتى مع استخراج PDF محليًا.</p></div></div>
              {([
                ['openai_api_key', 'مفتاح OpenAI', draft.openai_key_configured],
                ['llama_parse_api_key', 'مفتاح LlamaParse', draft.llamaparse_key_configured],
              ] as const).map(([name, label, configured]) => (
                <div className="setting-field" key={name}>
                  <div className="setting-label"><label htmlFor={name}>{label}</label><span className={configured && !remove[name] ? 'key-status configured' : 'key-status'}>{remove[name] ? 'سيُحذف عند الحفظ' : configured ? 'مفتاح محفوظ' : 'لم يُضف مفتاح'}</span></div>
                  <div className="secret-input">
                    <input id={name} type="password" autoComplete="new-password" dir="ltr" maxLength={4096} placeholder={configured ? 'اتركه فارغًا للاحتفاظ بالمفتاح الحالي' : 'أدخل مفتاح API'} value={keys[name]} disabled={remove[name] || saving} onChange={(event) => setKeys({ ...keys, [name]: event.target.value })} />
                    {configured && <button type="button" aria-label={remove[name] ? `التراجع عن حذف ${label}` : `حذف ${label}`} onClick={() => setRemove({ ...remove, [name]: !remove[name] })}>{remove[name] ? 'تراجع' : <Trash2 size={17} />}</button>}
                  </div>
                </div>
              ))}
              <p className="settings-hint"><ShieldCheck size={16} /><span>المفاتيح تُحفظ محليًا بحماية حساب ويندوز، ولا تُعرض بعد حفظها.</span></p>
            </section>
            <section className="settings-section">
              <div className="settings-section-title"><span><Settings2 size={20} /></span><div><h2>الموديلات</h2><p>التغييرات تُطبّق بعد الحفظ على العمليات الجديدة.</p></div></div>
              <div className="model-fields">
                {models.map(([name, label, description]) => (
                  <div className="setting-field" key={name}>
                    <label htmlFor={name}>{label}</label>
                    <input id={name} dir="ltr" required maxLength={512} value={draft[name]} disabled={saving || (name === 'embedding_model' && draft.embedding_locked)} onChange={(event) => setDraft({ ...draft, [name]: event.target.value })} />
                    <small>{name === 'embedding_model' && draft.embedding_locked ? 'أزل فهرسة الملفات المدرّبة قبل تغيير المودل، ثم درّبها مجددًا.' : description}</small>
                  </div>
                ))}
              </div>
            </section>
          </fieldset>
          <div className="settings-save-bar">
            <span>{busy ? 'انتظر اكتمال التدريب أو الإجابة الحالية للحفظ.' : dirty ? 'لديك تغييرات لم تُحفظ' : 'إعداداتك الحالية محفوظة'}</span>
            <button className="primary-button" type="submit" disabled={!dirty || saving || busy}>{saving ? <Loader2 size={17} className="spin" /> : <Save size={17} />}{saving ? 'جارٍ الحفظ…' : 'حفظ الإعدادات'}</button>
          </div>
        </form>
      )}
    </div>
  )
}
