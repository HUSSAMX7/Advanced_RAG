# Production readiness design interview

Status: first feature implemented and verified locally; backend restructuring
reviewed and committed. Supabase is connected locally and has accepted a real
email-link request; receipt and completed sign-in remain unverified. Later
production architecture branches remain open.
Started: 2026-10-13.

## ملخص الاستكمال للشات الجديدة

آخر تحديث: 2026-10-13. آخر كوميت: `fd1dd74` على فرع `develop`.

الهدف هو تجهيز المشروع للبرودكشن: رفع ملفات كبيرة، بيانات دائمة، مهام معالجة
في الخلفية، وقراءة وتحميل مع كثرة الطلبات. ننفّذ فيتشر واحدة ونختبرها ونعرضها
للمراجعة، ثم ننتظر موافقة المستخدم قبل تنفيذ التالية.

### المنجز

- تنفيذ الدخول الاختياري عبر رابط تحقق بالإيميل، وجلسات الضيف وعزل بيانات
  وإعدادات ومفاتيح كل حساب أو ضيف. مراجعة المتصفح استخدمت خدمة دخول وهمية؛
  إرسال الإيميل الحقيقي لم يُختبر بعد.
- الضيف يستخدم جميع الوظائف، ويظهر تنبيه تجديد كل 15 دقيقة مع مهلة دقيقة.
  تحديث الصفحة يحتفظ بالجلسة. إنهاؤها أو انتهاؤها يلغي العمل وينظّف البيانات.
  الإغلاق يستخدم إشعارًا بأفضل جهد ومهلة 15 ثانية لاستيعاب التحديث، مع انتهاء
  احتياطي إذا لم يصل الإشعار. لا نضمن حذفًا لحظيًا عند كل إغلاق للمتصفح.
- بيانات الضيف لا تنتقل إلى الحساب. المستخدم يوفّر مفاتيح خدماته؛ المفاتيح
  محفوظة مشفّرة وتظهر رسالة واضحة عند غياب مفتاح مطلوب.
- إعادة تنظيم FastAPI حسب الفيتشر: identity وassistants وfiles وconversations
  وsettings. كل فيتشر يجمع routes.py وschemas.py وservices.py وrepository.py.
  العمليات والتخزين فنكشنز بتبعيات واضحة؛ الكلاسات لحاجة فعلية موضّحة في
  [دليل الهيكلة](../architecture.md).
- نجحت الاختبارات المحلية الـ131، وفحوص Ruff والأنواع، وبناء الواجهة. هذه
  النتائج لا تثبت الإيميل الحقيقي أو أداء البرودكشن تحت الضغط.
- الكوميت يشمل التنفيذ والتوثيق. CONTEXT.md وAGENTS.md مستثنيان من الكوميت
  بناءً على طلب المستخدم وباقيان محليًا؛ .env والأسرار وبيانات التشغيل خارج Git.

### المتبقي بالترتيب المقترح

| المرحلة | العمل المتبقي | معيار المراجعة |
|---|---|---|
| إكمال الفيتشر الأولى | تأكيد وصول رابط التحقق وإكمال الدخول، ثم تجهيز إرسال البريد العام | تجربة رابط تحقق حقيقي، حسابين منفصلين، والخروج والعودة؛ إرسال لعناوين خارج فريق المشروع قبل اعتماد شرط أي إيميل |
| 2 — البيانات الدائمة | تصميم ونقل المساعدين والمحادثات ومعلومات الملفات إلى قاعدة بيانات مشتركة | عزل الملكية، استمرار البيانات بعد إعادة التشغيل، وخطة نقل البيانات الحالية |
| 3 — الملفات | تخزين خاص للملفات، رفع كبير قابل للاستكمال، وتحميل مصرح به | انقطاع الرفع واستكماله، منع الوصول لملف مستخدم آخر، وتنظيف الرفع غير المكتمل |
| 4 — المعالجة الخلفية | كيو دائمة وworkers مع التقدم والمحاولات والإلغاء وتنبيه الانتظار بسبب الضغط | استمرار المهمة بعد إعادة تشغيل الخادم، التعامل مع التسليم المكرر، والإلغاء الآمن |
| 5 — القراءة المتزامنة | تحديد طريقة الفهرسة والنشر والبحث أثناء التدريب ومع تعدد الطلبات | نتائج متسقة، منع ظهور فهرس جزئي، وقياس زمن البحث تحت حمل ممثل |
| 6 — التشغيل والسعة | اختيار الاستضافة، الحدود والمراقبة والنسخ الاحتياطي والاسترجاع | اختبار ضغط بأرقام واقعية، تنبيهات مفيدة، وتجربة استرجاع ناجحة |

هذه المراحل نطاق مقترح للمراجعة؛ تفاصيل كل مرحلة واختيار الخدمات تُحسم قبل
تنفيذها. Supabase Auth مدمج، أما Postgres وStorage وQueues وبديل FAISS فلم
تُعتمد أو تُنفّذ بعد. لا توجد استضافة منشورة أو دومين أو SMTP مجهّز.
الكود الحالي ما زال يستخدم SQLite وملفات محلية وFAISS ومهام داخل عملية واحدة.

### نقطة البداية في الشات الجديدة

1. اقرأ هذا الملف و[دليل الهيكلة](../architecture.md)، ثم افحص git status
   وتعليمات AGENTS.md المحلية. احفظ تغييرات المستخدم الموجودة.
2. ابدأ من [إعداد الدخول بالإيميل](../setup-email-signin.md): المستخدم أكد
   وجود مشروع `HUSSAMX7’s Project`، والصور تعرض حالة `Healthy`.
   القيم العامة مربوطة في `.env` الآن مع الاحتفاظ بمفتاح التشفير.
   نجح فحص Supabase Auth وفحص إعدادات التطبيق المحلي وبناء الواجهة.
   طلب رابط تحقق حقيقي من واجهة التطبيق قُبل وظهرت رسالة نجاح الطلب.
   المطلوب الآن تأكيد وصول الرسالة وإكمال الدخول في المتصفح نفسه الذي طلبها،
   والتحقق من إعداد Site URL وRedirect URLs على `http://127.0.0.1:8001/`.
   لم يُؤكد تجهيز دومين أو SMTP أو إعداد عناوين العودة في لوحة Supabase.
   المحاولات اللاحقة أرجعت `429` مع `over_email_send_rate_limit`؛ عائق
   التجربة الحالي هو حد إرسال البريد. عُدلت رسالة الواجهة ونجحت اختبارات
   الخطأ وبناء الواجهة وتجربة محلية محاكية. لا تكرر الإرسال دون سبب؛ راجع
   قسم عائق الإرسال في دليل الإعداد قبل متابعة التجربة الحقيقية.
3. استخدم .env.example وscripts/configure_identity.py للإعداد. مفتاح التشفير
   جُهّز محليًا بالفعل؛ احتفظ به ولا تعرض .env أو المفاتيح الخاصة في المخرجات.
4. أكمل التجربة الحقيقية للفيتشر الأولى أو وثّق اتفاق المستخدم الصريح على
   تأجيل إعدادها. لا تعتبر الموافقة على تنظيم الكود إثباتًا لنجاح إرسال البريد.
5. قبل تنفيذ المرحلة الثانية، حدد نطاقها ومعيار مراجعتها واحصل على موافقة
   المستخدم على الانتقال. عند تسليم كل فيتشر أعطه روابط الفنكشنز بترتيب
   مسار الطلب، الحالات المهمة، نتائج الاختبارات وطريقة التجربة اليدوية.

نص جاهز لبداية الشات الجديدة:

> اقرأ docs/specs/production-readiness.md وdocs/architecture.md وتعليمات
> AGENTS.md، وافحص حالة المشروع. كمل معي من نقطة البداية الموثقة، فيتشر
> فيتشر، ولا تبدأ التالية إلا بعد موافقتي. ابدأ بإكمال إعداد وتجربة الدخول
> الحقيقي بالإيميل حسب الوضع الحالي.

## Objective

Design production operation for large uploads, durable processing jobs, shared
persistent data, and concurrent document retrieval and file downloads. Record
agreed domain terms in CONTEXT.md and consequential architecture decisions in
docs/adr/ as the interview resolves them.

## Verified local baseline

- Uploads pass through FastAPI and are copied to local disk in 1 MiB blocks
  (src/advanced_rag/web/files/services.py, upload). The default limit is 50 MiB per file
  (src/advanced_rag/config.py:40). Downloads use FileResponse
  (src/advanced_rag/web/files/routes.py, download).
- File metadata and processing status already live in SQLite, separately from
  original file bytes (src/advanced_rag/web/files/repository.py).
- Conversation history lives in JSON files
  (src/advanced_rag/agent/sessions.py:30).
- One application process owns the data directory, enforced with .app.lock
  (src/advanced_rag/web/app.py, workspace lifespan).
- Training runs as in-process asyncio tasks. Queued status is persisted in
  SQLite; startup reschedules queued files and marks interrupted running work
  failed (src/advanced_rag/web/files/processing.py, start and train).
- Assistant libraries share an operation lock. Full training holds that lock,
  and retrieval-context acquisition waits for it
  (src/advanced_rag/web/assistants/services.py, get_library;
  src/advanced_rag/web/files/processing.py, _train and context).
- Retrieval uses local FAISS IndexFlatL2 and an in-memory BM25 corpus
  (src/advanced_rag/storage.py:125;
  src/advanced_rag/retrieval/search.py:21).
- Existing domain language distinguishes upload from Training, and Training
  means indexing rather than changing model weights (CONTEXT.md).

## Confirmed requirements

- Sign-in is optional; visitors may use the application as guests.
- Guests have all core functionality, including assistants, files, training and
  chat, and may set their own provider API keys and model settings.
- Every 15 minutes, show the guest a renewal prompt with a suggestion to create
  an account. Renewal keeps the guest workspace. A 60-second no-response grace
  ends in revocation, cancellation and cleanup. Reload retains the session and
  deadline; close/reopen starts fresh, with best-effort close reporting and
  server expiry as fallback. Each guest tab has an independent workspace.
- Guest data is discarded rather than transferred into an account on sign-in.
  A new account starts without the guest's assistants, files or conversations.
  Signing in to an existing account must expose only that account's data.
- Signed-in users own private data. There are no team/shared libraries.
- Sign-in uses only an email verification message, without a password. The
  initial implementation sends a verification link, as stated before execution.
- Service settings and credentials are private to each account or guest
  session. Users may set their own OpenAI/LlamaParse keys and model preferences;
  one owner's updates must not change another owner's runtime settings.
- Account provider keys persist encrypted. Guests' keys are deleted with their
  sessions. Users supply their own keys; missing keys return service-specific
  guidance rather than using server credentials.
- File preparation may wait in the background. The user should receive a
  meaningful notice when server load delays processing.
- Delivery is one feature at a time. Implement and verify that feature, present
  it for review, and wait for the user's explicit approval before starting the
  next implementation feature. This gate was explicitly requested by the user.

## Reported environment and unresolved capacity

On 2026-10-13, the user confirmed an existing Supabase project. Their screenshots
show `HUSSAMX7’s Project` with status `Healthy`; the publishable key is truncated.
The user then supplied the complete public project values, which were saved to
the ignored `.env` with `scripts/configure_identity.py`, retaining the existing
credential encryption key. Supabase `/auth/v1/settings` returned HTTP 200 with
email enabled, signup allowed and email auto-confirm disabled. The local
`/api/auth/config` returned HTTP 200 with identity enabled and matching project
values. The frontend production build passed and the local server started at
`http://127.0.0.1:8001/`. A real email-link request from the in-app browser was
accepted and the UI displayed its success notice. Receipt, redirect behavior
and completed sign-in are still unverified. Keep the requesting browser session
for PKCE; do not request a second email without a reason. No Supabase dashboard
tab is connected to this chat, so Site URL, allowed redirects and SMTP settings
have not been inspected. Domain and SMTP provisioning have not been confirmed.
The baseline application used local SQLite, files and FAISS without Supabase.
Feature 1 adds Supabase Auth integration and owner-specific local workspaces.
Backend and frontend hosting remain undecided; no deployment or purchase has
been confirmed.

Traffic and file-volume estimates are unknown. Establish configurable admission
and concurrency limits, then measure representative ingestion and retrieval
workloads. Example worker counts or queue lengths are illustrations, not capacity
promises. Watch memory, CPU, job duration, queue age, search latency, database load,
and upstream model/OCR rate limits before raising concurrency.

## Current decision frontier

Supabase is connected locally and a real email-link request has been accepted.
Confirm receipt, verify local redirect configuration, complete sign-in in the
requesting browser, and validate the remaining live review cases and general
SMTP delivery. Review Feature 1 with the user before beginning the next
implementation feature. See
[Feature 1](identity-and-guest-sessions.md). Capacity and hosting decisions remain
open for their subsequent design rounds.

The current live blocker is HTTP 429 with `over_email_send_rate_limit`, captured
from the actual Supabase SDK error. Email error guidance was corrected and
verified with four regression tests, a production frontend build and a local
HTTP 429 replay in both entry and guest-dialog flows. Debug instrumentation was
removed. Live quota reset timing and SMTP settings have not been inspected;
wait for sending availability or configure production SMTP before another live
delivery attempt. No later feature is authorized by this fix.

Questions dependent on these answers wait until their prerequisites are settled.

## Proposed review sequence

This sequence is a proposal, not authorization to implement every feature now.

1. Identity and access: optional sign-in, renewable guest behavior, ownership
   checks and isolated owner-specific settings needed to exercise the existing
   application safely. Full database/file/queue migration remains separate.
2. Durable application records: assistants, conversations and document metadata.
3. File lifecycle: private storage, uploads, resumability and downloads.
4. Durable background preparation: jobs, worker execution, progress, retries and
   cancellation.
5. Concurrent retrieval: indexed content, publication and read isolation.
6. Capacity and operations: measured limits, overload behavior, monitoring,
   backups and recovery validation.

Each feature must declare prerequisites and deliver a reviewable working scope.
If one feature requires an earlier infrastructure change, adjust its scope and
sequence explicitly instead of silently implementing later features.

## Subsequent branches

After their prerequisites are settled, resolve file versus document identity,
versions and duplicate uploads; upload completion and resumability; processing
states, retries, cancellation and publication; authorization and isolation;
database, object storage and retrieval backend choices; queue delivery and worker
ownership; read scaling and resource limits; deletion and source availability;
backups, recovery and migration; observability and rollout acceptance criteria.

## References checked

[MDN pagehide documentation](https://developer.mozilla.org/en-US/docs/Web/API/Window/pagehide_event)
states that page closure notifications are not reliable, particularly on mobile.
Immediate server-side deletion on every browser close cannot be guaranteed.
Explicit session exit can revoke access and initiate deletion; missed closures
need an agreed server-side expiration and cleanup mechanism. Cleanup must cover
originals, derived images, indexes, assistants, conversations and outstanding
processing work. A best-effort browser signal alone does not satisfy this policy.

[Supabase passwordless email authentication](https://supabase.com/docs/guides/auth/auth-email-passwordless)
supports emailed verification codes and links. For verification delivery to
arbitrary email addresses, configure a production email sending service;
[the default Supabase SMTP service](https://supabase.com/docs/guides/auth/auth-smtp)
is restricted to project team addresses. Email delivery setup is a prerequisite
for validating the confirmed any-email sign-in requirement.

Supabase Auth is integrated for Feature 1. Its other services remain candidates
for later reviewed features. Documented capabilities include
[Auth](https://supabase.com/docs/guides/auth),
[resumable file uploads](https://supabase.com/docs/guides/storage/uploads/resumable-uploads),
[Postgres-based durable queues](https://supabase.com/docs/guides/queues), and
[pgvector](https://supabase.com/docs/guides/ai/vector-columns).
Queue delivery does not itself execute Python processing or guarantee a job's
side effects happen only once; worker execution and safe retries need explicit
design. Separate application records from original file storage, and enqueue
references to processing work rather than complete file bytes.

The platform's
[anonymous sign-in](https://supabase.com/docs/guides/auth/auth-anonymous)
creates a persisted anonymous auth user; it does not automatically enforce the
product requirement for temporary guest data. Guest expiration and cleanup must
be designed if temporary storage is allowed.

## First-feature implementation facts

Each owner's SettingsState stores its own settings.json. Provider credentials
use Fernet when WEB_CREDENTIAL_ENCRYPTION_KEY is configured, with Windows
user-scoped DPAPI retained for existing local installations
(src/advanced_rag/web/settings/credentials.py). The settings services update
that owner's assistant libraries and enforce owner-specific busy/index checks
(src/advanced_rag/web/settings/services.py). The identity gateway isolates owner
storage and runtime values. Linux hosting must configure the portable encryption
key; live deployment and distributed processing remain later work.

[Amazon S3 multipart upload overview](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html)
describes uploading parts independently, retrying failed parts, and pausing and
resuming uploads. This is an option to evaluate after workload and hosting
constraints are agreed; it does not select AWS as the deployment provider.
