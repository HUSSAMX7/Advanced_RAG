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
├── retrieval/                # FAISS + BM25 + RRF ثم BGE reranking محلي
├── agent/                    # إيجنت OpenAI وشات الطرفية وحفظ الجلسات
├── storage.py                # embeddings وحفظ فهرس FAISS وتحميله
├── models.py                 # بيانات الملف وحالة المعالجة
├── config.py                 # إعدادات الاتصال
└── cli.py                    # تشغيل البايب لاين
```

`process_pdfs` ينسق المعالجة وحالات الملفات. `create_chunks` يجمع استخراج الأقسام
وربطها بالصفحات ثم التقسيم، دون تخزين. `storage.py` يتعامل مع الفهرس المحفوظ.
الاختبارات مرتبة حسب نفس المهام: المزوّدات، الأقسام، التقسيم، البايب لاين، التخزين والتشغيل.

## التشغيل

### واجهة المكتبة والشات

الواجهة عربية مبنية بـReact وTypeScript. تفتح على الشات، وفي السايد بار المكتبة،
محادثة جديدة، والمحادثات السابقة. يمكنك سؤال المودل مباشرة دون رفع أو تدريب ملفات.
المكتبة محلية واحدة بدون حسابات؛ يبحث الشات في جميع ملفاتها المفهرسة عندما يحتاج
السؤال إلى محتواها. الصيغ المدعومة: PDF وDOCX وDOC وTXT (UTF-8).

```powershell
uv sync
Copy-Item .env.example .env  # مرة واحدة إذا لم يكن لديك .env
npm --prefix frontend ci
npm --prefix frontend run build
uv run advanced-rag-web
```

افتح `http://127.0.0.1:8001`. يتطلب بناء الواجهة Node.js 20.19+ أو 22.12+.
للتطوير شغّل الخادم، ثم `npm --prefix frontend run dev` في طرفية ثانية؛
Vite يمرر طلبات `/api` إلى الخادم المحلي.

- رفع الملف يحفظه فقط؛ اضغط **تدريب** لاستخراج النص وتقسيمه وحفظ المتجهات.
- يظهر **تم التدريب** بعد تفعيل الفهرس المكتمل فقط. يمكنك متابعة مراحل
  الاستخراج والتقسيم والحفظ؛ الملفات المنتظرة تُعالج بالتتابع.
- **إيقاف** يلغي التدريب المنتظر أو الجاري. أثناء طلب embeddings بدأ بالفعل،
  ينتظر إتمام الطلب ثم يتخلص من النتيجة دون نشرها في الفهرس.
- **إزالة الفهرسة** تخرج مقاطع الملف من البحث وتحتفظ بالملف الأصلي؛
  **حذف الملف** يزيل الأصل ومقاطعه. المحادثات السابقة تبقى محفوظة.
- مصادر الإجابة تعرض اسم الملف، والصفحة إن وجدت، والمقطع المستخدم.
  مصدر أُزيل من الفهرس يظهر كمصدر غير متوفر عند فتحه من إجابة قديمة.
- ملفات فُهرست سابقًا عبر CLI تظهر في المكتبة، لكن تنزيل الأصل وإعادة التدريب
  يتطلبان إعادة رفعه إذا لم يكن الأصل محفوظًا فيها.

تستخدم DOCX الفقرات والجداول بترتيبها الأصلي؛ لا تستخرج النص من الصور المضمنة.
ملفات DOC القديمة تحتاج [LibreOffice](https://www.libreoffice.org/download/download-libreoffice/)
لتحويلها تلقائيًا إلى DOCX بوضع خفي. يُكتشف في مسارات Windows المعتادة، أو اضبط
`LIBREOFFICE_PATH`. مهلة التحويل دقيقتان. باقي الصيغ تعمل دون LibreOffice.

`WEB_DATA_DIR` افتراضيًا `storage/library` للملفات وSQLite، و`MAX_UPLOAD_BYTES`
افتراضيًا 50 MiB لكل ملف. مفاتيح OpenAI والاستخراج تبقى في الخادم، ولا تُرسل
إلى المتصفح. ملفات TXT وWord تحتاج OpenAI للـembeddings والشات؛ PDF يحتاج أيضًا
إعداد مزوّد الاستخراج المذكور أدناه.

الخادم يستخدم عامل تشغيل واحدًا؛ قفل المكتبة يمنع تشغيل خادمين على نفس بياناتها.
الفهرس يُحفظ في نسخ مرحلية، ثم يُفعّل بمؤشر ذري. الإلغاء قبل التفعيل لا يغيّر
الفهرس السابق، وإعادة المحاولة لن تكرر مقاطع الملف. حذف المقاطع يعيد بناء الفهرس
من المتجهات المتبقية دون إعادة embeddings. البحث يُحدّث عند تغير الفهرس، وتُراجع
حالات الملفات والعمليات غير المكتملة عند إعادة تشغيل الخادم.

يتطلب Python 3.13 و`uv`.

```powershell
uv sync
Copy-Item .env.example .env
```

اضبط `OPENAI_API_KEY` للأقسام والـembeddings، ثم إعدادات المزوّد:

- `llamaparse`: اضبط `LLAMA_PARSE_API_KEY`.
- `lightonocr`: اضبط `LIGHTONOCR_URL` لعنوان خادم النموذج.

`LIGHTONOCR_URL` يمكن أن يكون محليًا، مثل
`http://localhost:8000/v1/chat/completions`. المشروع يتصل بخادم منفصل يشغّل
LightOnOCR (واجهة متوافقة مع OpenAI، مثل vLLM) حتى عندما يعمل على نفس الجهاز.
كتابة العنوان لا تشغّل خادم OCR؛ يجب تشغيله أولًا. يستخدمه استخراج PDF فقط عند
اختيار `PDF_PROVIDER=lightonocr` أو تمرير `--provider lightonocr`.

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
تكامل FAISS المستخدم لا يدعم فلترة metadata أو حذف المستندات مباشرة؛ إزالة ملف
من المكتبة تعيد بناء الفهرس من المتجهات المتبقية. التخزين مخصص للتشغيل المحلي،
مع قفل يمنع أكثر من عملية كتابة على مجلد الفهرس في كل مرة.

## سؤال الإيجنت

بعد إدخال ملفات PDF، ضع `OPENAI_API_KEY` وشغّل:

```powershell
uv run advanced-rag-chat
uv run advanced-rag-chat --question "كم قيمة الفاتورة ZX-774؟"
uv run advanced-rag-chat --session "معرّف-الجلسة-الذي-ظهر-لك"
uv run advanced-rag-chat --persist-dir storage/pdf_documents --sessions-dir chat_sessions
```

للخروج من الشات اكتب `/exit`. النتيجة تعرض الإجابة، مراجع الملفات وأرقام الصفحات،
ومعرّف الجلسة UUID. استخدام `--session` يتطلب جلسة محفوظة؛ لا ينشئ جلسة بديلة عند الخطأ.
تُحفظ الأسئلة والإجابات والمصادر محليًا في `chat_sessions/`، ويستخدم الإيجنت آخر
10 تبادلات لفهم المتابعة. لا يُحفظ السؤال الذي فشل تنفيذه، ويظل تاريخ الجلسة كاملًا.
شغّل عملية شات واحدة لكل جلسة في كل مرة.

يجيب المودل عن الأسئلة العامة مباشرة. أداة `search_documents` تبحث عند الحاجة
مرة واحدة لكل سؤال متعلق بملفاتك في جميع ملفات الفهرس. تجمع حتى
20 نتيجة من المتجهات و20 من الكلمات، تدمجها بـRRF، ثم ترتّب أفضل 20 عبر BGE محليًا
وترجع أفضل 5. يستخدم الإيجنت OpenAI SDK مباشرة دون LangChain أو Agents SDK.
بحث واحد لا يعني طلب OpenAI واحدًا: توجد طلبات صياغة استعلام الأداة، embedding
للسؤال وتوليد الإجابة؛ ترتيب النتائج محلي ولا يستدعي OpenAI.

`AGENT_MODEL` افتراضيًا `gpt-4o-mini`، و`RERANK_MODEL` افتراضيًا
`BAAI/bge-reranker-v2-m3` ([صفحة النموذج](https://huggingface.co/BAAI/bge-reranker-v2-m3)).
يشغّل BGE عبر `sentence-transformers` على CPU، ويحمّله مرة واحدة عند أول بحث
ويحتفظ به في الذاكرة. تنزيل الأوزان أول مرة يحتاج اتصالًا بالإنترنت؛ التشغيل
التالي يستخدم ذاكرة Hugging Face المحلية. يمكن وضع مسار مجلد نموذج محلي في
`RERANK_MODEL`. إصدار PyTorch المثبت مخصص للمعالج.
`RERANK_BATCH_SIZE` افتراضيًا 1 لتقليل الذاكرة، و`RERANK_MAX_LENGTH` افتراضيًا
2048 رمزًا لكل زوج سؤال/مقطع؛ النصوص الأطول تُقتطع أثناء تقييم الصلة، وتبقى
المقاطع الأصلية كاملة في الإجابة. قد يكون الترتيب بطيئًا على CPU؛ ينفّذ خارج
حلقة الخادم، بالتتابع لمنع تحميل نسخ متعددة من النموذج.
يمكن تعديل أعداد النتائج عبر
`RETRIEVAL_CANDIDATES` و`RETRIEVAL_TOP_K`. تطبيع الكلمات العربية والإنجليزية يحدث
داخل البحث اللفظي فقط؛ النص الأصلي والأرقام والتواريخ تبقى كما هي. يُبنى BM25 من
الفهرس عند بدء الشات؛ أعد فتح الشات بعد إضافة مستندات جديدة.

للاستخدام من Python:

```python
import asyncio
from dotenv import load_dotenv
from openai import AsyncOpenAI
from advanced_rag import Settings
from advanced_rag.agent import ask_agent
from advanced_rag.config import require_openai_key
from advanced_rag.retrieval import load_search_context

async def main():
    load_dotenv()
    settings = Settings()
    context = load_search_context(settings)
    async with AsyncOpenAI(api_key=require_openai_key(settings)) as client:
        result = await ask_agent("ما تفاصيل الفاتورة؟", context=context,
                                 client=client, settings=settings)
        print(result["answer"], result["sources"], result["session_id"])
        # مرّر session_id=result["session_id"] للسؤال التالي لاستكمال المحادثة.

asyncio.run(main())
```

الـreranking غير الصالح أو أخطاء API تتوقف بخطأ واضح؛ لا تُرجع نتائج غير مرتبة
بصمت. تُراجع معرّفات المصادر وأرقام المراجع قبل حفظ الإجابة. توجيه الإيجنت هو
التصريح عند عدم كفاية الأدلة؛ صحة صياغة الإجابة تحتاج تقييمًا على مستنداتك الفعلية.

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
uv run ruff check src/advanced_rag/agent src/advanced_rag/retrieval tests
uvx ty check src/advanced_rag/agent src/advanced_rag/retrieval src/advanced_rag/config.py
```

الاختبارات تستخدم استجابات وهمية وFAISS فعليًا داخل مجلدات مؤقتة؛ لا تستدعي خدمات الاستخراج
أو OpenAI الفعلية.
