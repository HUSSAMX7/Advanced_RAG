# Advanced RAG — PDF

جزئية PDF من الملفات المرفقة، مع ربطها بالمشروع. كود الأقسام وLightOnOCR منقول
كما هو؛ بقية الملفات تفصل الاستخراج والتقسيم والتخزين وإعدادات التشغيل.
التخزين المحلي يستخدم FAISS بدل Qdrant.

```text
PDF → LlamaParse / LightOnOCR → استخراج الأقسام ومراجعتها بالـLLM
    → ربط الأقسام بالصفحات → SentenceSplitter (1024 / overlap 50) → FAISS
```

## الملفات

```text
src/advanced_rag/
├── ingestion/                # إدخال PDF وتجهيز مقاطعه
│   ├── providers/
│   │   ├── llamaparse.py     # استخراج الصفحات عبر LlamaParse
│   │   └── lightonocr.py     # LightOnOCR الأصلي، بما فيه postprocess
│   ├── sections.py          # استخراج الأقسام ومراجعتها وربطها الأصلي
│   ├── chunking.py          # create_chunks: الأقسام ثم SentenceSplitter
│   └── pipeline.py          # الاستخراج ثم تجهيز المقاطع ثم الحفظ
├── storage.py                # embeddings وحفظ فهرس FAISS وتحميله
├── models.py                 # بيانات الملف وحالة المعالجة
├── config.py                 # إعدادات الاتصال
└── cli.py                    # تشغيل البايب لاين
```

`process_pdfs` ينسق المعالجة وحالات الملفات. `create_chunks` يجمع استخراج الأقسام
وربطها بالصفحات ثم التقسيم، دون تخزين. `storage.py` يتعامل مع الفهرس المحفوظ.
الاختبارات مرتبة حسب نفس المهام: المزوّدات، الأقسام، التقسيم، البايب لاين، التخزين والتشغيل.

## التشغيل

يتطلب Python 3.13 و`uv`.

```powershell
uv sync
Copy-Item .env.example .env
```

اضبط `OPENAI_API_KEY` للأقسام والـembeddings، ثم إعدادات المزوّد:

- `llamaparse`: اضبط `LLAMA_PARSE_API_KEY`.
- `lightonocr`: اضبط `LIGHTONOCR_URL` لعنوان خادم النموذج.

```powershell
uv run main.py "D:/documents/report.pdf"
uv run main.py "D:/documents/report.pdf" --provider lightonocr
```

يمكن تمرير أكثر من ملف. التشغيل يحفظ المقاطع محليًا ويطبع حالة كل ملف بصيغة
JSON: `file_id` و`file_name` و`success` و`error`. الخيارات الأخرى:
`--persist-dir` و`--assistant-id`.

مسار الحفظ الافتراضي `storage/pdf_documents`، ويُضبط عبر `FAISS_PERSIST_DIR`
أو `--persist-dir`. يُحفظ الفهرس مع النصوص والـmetadata وربطها بالمتجهات.
التشغيل التالي يحمّل الفهرس ويضيف المقاطع الجديدة. استخدم نفس نموذج embeddings
عند الإضافة والاسترجاع؛ تغيير النموذج يتطلب مسارًا جديدًا وإعادة الفهرسة.

```python
from dotenv import load_dotenv
from advanced_rag import Settings
from advanced_rag.storage import load_faiss_index

load_dotenv()
index = load_faiss_index(Settings())
results = index.as_retriever(similarity_top_k=5).retrieve("سؤال عن المستند")
```

الفهرس `IndexFlatL2` يبحث بحثًا دقيقًا في كل المتجهات. وقت البحث واستهلاك الذاكرة
يزيدان مع عدد المقاطع. درجات النتائج مسافات L2 مربعة؛ الأقل أقرب.
تكامل FAISS المستخدم لا يدعم فلترة metadata أو حذف المستندات؛ التخزين مخصص
للتشغيل المحلي، مع عملية كتابة واحدة على مجلد الفهرس في كل مرة.

الأقسام تستخدم `gpt-4o-mini` كما في الأصل، وتُربط بالصفحات حسب رقم بداية القسم.
إذا لم تُستخرج أقسام، يُستخدم `0: اسم الملف`.

`postprocess` موجود داخل LightOnOCR فقط، ويمكن تعطيله بإعداد
`LIGHTONOCR_POSTPROCESS=false`. الكود الأصلي ينظف التكرار وبعض الكلمات العربية
وجداول HTML، ويتجاوز الصفحات القصيرة والصفحات التي يفشل OCR فيها.

إعدادا LlamaParse الأصليان `tier` و`version` محفوظان؛ نسخة SDK المثبتة `0.6.54`
تصدر تنبيهًا بأنها تتجاهلهما.

## التحقق المحلي

```powershell
uv run pytest -q
```

الاختبارات تستخدم استجابات وهمية وFAISS فعليًا داخل مجلدات مؤقتة؛ لا تستدعي خدمات الاستخراج
أو OpenAI الفعلية.
