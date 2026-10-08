import { useRef, useState } from 'react'
import {
  ArrowUpRight,
  Check,
  CheckCircle2,
  FileText,
  FolderOpen,
  Loader2,
  Search,
  Trash2,
  UploadCloud,
  X,
  Download,
  RotateCcw,
  CircleDashed,
  Ban,
} from 'lucide-react'
import { busyStatus, formatSize, type Health, type LibraryFile } from '../api'

interface Props {
  files: LibraryFile[]
  health: Health | null
  uploading: string | null
  actions: Set<string>
  onUpload: (files: File[]) => void
  onAction: (file: LibraryFile, action: 'train' | 'cancel' | 'unindex' | 'delete') => void
  onChat: () => void
}

const statuses = {
  untrained: 'لم يتم التدريب',
  queued: 'بانتظار التدريب',
  training: 'جارٍ التدريب',
  cancelling: 'جارٍ الإلغاء',
  trained: 'تم التدريب',
  failed: 'فشل التدريب',
  cancelled: 'تم الإلغاء',
}
const stages: Record<string, string> = {
  describing_images: 'تجهيز الصور وتوصيفها',
  preparing_ocr: 'تجهيز LightOnOCR المحلي',
  extracting: 'استخراج النص',
  chunking: 'تقسيم إلى مقاطع',
  storing: 'إنشاء المتجهات وحفظها',
}

export default function Library(props: Props) {
  const input = useRef<HTMLInputElement>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const [deleting, setDeleting] = useState<LibraryFile | null>(null)
  const [dragging, setDragging] = useState(false)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const trained = props.files.filter((file) => file.status === 'trained').length
  const working = props.files.filter((file) => busyStatus(file.status)).length
  const filtered = props.files.filter(
    (file) =>
      file.name.toLowerCase().includes(query.toLowerCase()) &&
      (filter === 'all' ||
        (filter === 'trained' ? file.status === 'trained' : file.status !== 'trained')),
  )

  function askDelete(file: LibraryFile) {
    setDeleting(file)
    dialog.current?.showModal()
  }

  return (
    <div className="library-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">مصادرك، في مكان واحد</div>
          <h1>
            مكتبة المعرفة<span className="heading-dot">.</span>
          </h1>
          <p>ارفع مستنداتك، درّبها، وابدأ محادثة تستند إلى محتواها.</p>
        </div>
        <button className="button secondary" onClick={props.onChat}>
          انتقل للشات <ArrowUpRight size={17} />
        </button>
      </div>
      <div className="library-stats">
        <div>
          <span className="stat-icon neutral">
            <FolderOpen size={21} />
          </span>
          <div>
            <span>ملفات المكتبة</span>
            <strong>{props.files.length.toLocaleString('ar-SA')}</strong>
          </div>
        </div>
        <div>
          <span className="stat-icon green">
            <CheckCircle2 size={21} />
          </span>
          <div>
            <span>جاهزة للمحادثة</span>
            <strong>{trained.toLocaleString('ar-SA')}</strong>
          </div>
        </div>
        <div>
          <span className="stat-icon amber">
            <CircleDashed size={21} />
          </span>
          <div>
            <span>قيد التجهيز</span>
            <strong>{working.toLocaleString('ar-SA')}</strong>
          </div>
        </div>
      </div>
      <div
        className={`upload-zone ${dragging ? 'dragging' : ''} ${props.uploading ? 'uploading' : ''}`}
        onDragOver={(event) => {
          event.preventDefault()
          if (!props.uploading) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          if (!props.uploading && props.health) props.onUpload(Array.from(event.dataTransfer.files))
        }}
      >
        <span className="upload-icon">
          {props.uploading ? <Loader2 size={29} className="spin" /> : <UploadCloud size={29} />}
        </span>
        <div>
          <h2>{props.uploading ? 'جارٍ رفع الملف…' : 'أضف مصدرًا جديدًا لمعرفتك'}</h2>
          <p>{props.uploading ?? 'اسحب ملفاتك هنا، أو اخترها من جهازك'}</p>
          <span className="upload-types" dir="ltr">
            PDF · DOCX · DOC · TXT <i />{' '}
            {formatSize(props.health?.max_upload_bytes ?? 50 * 1024 * 1024)} / ملف
          </span>
        </div>
        <button
          className="button primary"
          disabled={!!props.uploading || !props.health}
          onClick={() => input.current?.click()}
        >
          <UploadCloud size={17} /> اختر الملفات
        </button>
        <input
          ref={input}
          className="sr-only"
          type="file"
          multiple
          accept=".pdf,.docx,.doc,.txt"
          aria-label="رفع ملفات إلى المكتبة"
          onChange={(event) => {
            props.onUpload(Array.from(event.target.files ?? []))
            event.target.value = ''
          }}
        />
      </div>
      {props.health && !props.health.doc_available && (
        <div className="info-line">
          <FileText size={15} /> ملفات DOC القديمة تحتاج تثبيت LibreOffice؛ ملفات PDF وDOCX وTXT
          جاهزة للاستخدام.
        </div>
      )}
      <div className="files-section">
        <div className="files-toolbar">
          <div className="files-title">
            <h2>ملفاتك</h2>
            <span>{props.files.length}</span>
          </div>
          <label className="search-input">
            <Search size={17} />
            <input
              aria-label="البحث في أسماء الملفات"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="ابحث عن ملف…"
            />
          </label>
        </div>
        <div className="files-tabs" role="group" aria-label="تصفية الملفات">
          {[
            ['all', 'كل الملفات'],
            ['trained', 'تم التدريب'],
            ['pending', 'غير مدربة'],
          ].map(([value, label]) => (
            <button
              key={value}
              className={filter === value ? 'active' : ''}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
        {!filtered.length ? (
          <div className="empty-library">
            <span>
              <FolderOpen size={35} strokeWidth={1.3} />
            </span>
            <h3>{props.files.length ? 'لا توجد ملفات مطابقة' : 'مكتبتك تنتظر أول ملف'}</h3>
            <p>
              {props.files.length
                ? 'جرّب اسمًا آخر أو غيّر التصفية.'
                : 'أضف ملفًا ثم اضغط «تدريب» ليصبح مصدرًا لإجاباتك.'}
            </p>
          </div>
        ) : (
          <div className="file-table" role="table" aria-label="ملفات المكتبة">
            <div className="file-table-header" role="row">
              <span>الملف</span>
              <span>الحالة</span>
              <span>الإجراءات</span>
            </div>
            {filtered.map((file) => (
              <div className="file-row" role="row" key={file.id}>
                <div className="file-info" role="cell">
                  <span className={`file-type-icon ${file.type}`}>
                    <FileText size={23} />
                    <small>{file.type.toUpperCase()}</small>
                  </span>
                  <div>
                    <strong title={file.name}>{file.name}</strong>
                    <span dir="auto">
                      {formatSize(file.size)}
                      <i />
                      {file.status === 'trained'
                        ? `${file.chunks} مقطع`
                        : new Date(file.created_at).toLocaleDateString('ar-SA', {
                            day: 'numeric',
                            month: 'short',
                            calendar: 'gregory',
                          })}
                    </span>
                  </div>
                </div>
                <div className="file-state" role="cell">
                  <span className={`status-pill ${file.status}`}>
                    {file.status === 'trained' ? (
                      <Check size={13} />
                    ) : busyStatus(file.status) ? (
                      <Loader2 size={13} className="spin" />
                    ) : (
                      <span className="status-dot" />
                    )}
                    {statuses[file.status]}
                  </span>
                  {file.stage && <small>{file.stage.startsWith('ocr_page:') ? `قراءة صفحة ${file.stage.split(':')[1]} من ${file.stage.split(':')[2]}` : stages[file.stage] ?? file.stage}</small>}
                  {file.warning && <small className="file-warning">{file.warning}</small>}
                  {file.error && (
                    <small className="file-error" title={file.error}>
                      {file.error}
                    </small>
                  )}
                </div>
                <div className="file-actions" role="cell">
                  {props.actions.has(file.id) ? (
                    <span className="action-loading">
                      <Loader2 size={17} className="spin" /> جارٍ التنفيذ
                    </span>
                  ) : busyStatus(file.status) ? (
                    <button
                      className="button small quiet"
                      disabled={file.status === 'cancelling'}
                      onClick={() => props.onAction(file, 'cancel')}
                    >
                      <X size={14} /> إيقاف
                    </button>
                  ) : file.status === 'trained' ? (
                    <button
                      className="button small quiet"
                      onClick={() => props.onAction(file, 'unindex')}
                    >
                      <Ban size={14} /> إزالة الفهرسة
                    </button>
                  ) : (
                    <button
                      className="button small train"
                      disabled={!file.has_original}
                      title={!file.has_original ? 'أعد رفع الملف لتدريبه' : undefined}
                      onClick={() => props.onAction(file, 'train')}
                    >
                      {file.status === 'failed' || file.status === 'cancelled' ? (
                        <RotateCcw size={14} />
                      ) : (
                        <span className="training-star">✦</span>
                      )}
                      {file.status === 'failed' || file.status === 'cancelled'
                        ? 'إعادة المحاولة'
                        : 'تدريب'}
                    </button>
                  )}
                  {file.has_original && (
                    <a
                      href={`/api/files/${file.id}/download`}
                      className="icon-button file-download"
                      aria-label={`تنزيل ${file.name}`}
                      title="تنزيل الملف"
                    >
                      <Download size={16} />
                    </a>
                  )}
                  <button
                    className="icon-button delete-button"
                    disabled={props.actions.has(file.id)}
                    aria-label={`حذف ${file.name}`}
                    title="حذف الملف"
                    onClick={() => askDelete(file)}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="library-footer">
          <CheckCircle2 size={14} /> الملفات المدربة فقط تُستخدم في المحادثات. رفع الملف لا يبدأ
          التدريب تلقائيًا.
        </div>
      </div>
      <dialog
        ref={dialog}
        className="confirm-dialog"
        onCancel={() => setDeleting(null)}
        onClick={(event) => {
          if (event.target === event.currentTarget) dialog.current?.close()
        }}
      >
        <div className="dialog-icon">
          <Trash2 size={25} />
        </div>
        <h2>حذف الملف من المكتبة؟</h2>
        <p>
          سيُحذف <strong dir="auto">{deleting?.name}</strong> ومقاطعه من البحث. تبقى المحادثات
          السابقة محفوظة.
        </p>
        <div className="dialog-actions">
          <button
            className="button danger"
            onClick={() => {
              if (deleting) props.onAction(deleting, 'delete')
              dialog.current?.close()
              setDeleting(null)
            }}
          >
            حذف الملف
          </button>
          <button
            className="button secondary"
            onClick={() => {
              dialog.current?.close()
              setDeleting(null)
            }}
          >
            تراجع
          </button>
        </div>
      </dialog>
    </div>
  )
}
