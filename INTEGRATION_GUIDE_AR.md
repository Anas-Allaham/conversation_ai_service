# دليل دمج مشروع المدرّس مع باك إند الفريق

## ما الذي تغيّر؟

أصبح باك إند الفريق هو المشروع الأساسي فعلًا. أضيفت إليه مكونات مشروع المدرّس
من دون تغيير مسارات الفريق القديمة أو طريقة تخزين محادثاته:

- تطبيق FastAPI واحد على المنفذ `8000`.
- قاعدة واحدة يحددها `DATABASE_URL`: SQLite للتجربة المحلية، وPostgreSQL
  لبيئة الفريق والإنتاج.
- عامل `english-tutor` واحد يشغّل المحادثة الحرة أو المقيدة حسب metadata موثوقة
  يصدرها الباك إند.
- عامل مستقل باسم `english-level-assessor` للتقييم الشفهي.
- لا حاجة لتشغيل خدمة تقييم مستقلة على المنفذ `8080`، ولا حاجة إلى قاعدة
  `assessment.db` منفصلة.

لم يعد الملف القديم المستقل `voice_agent.py` نقطة التشغيل. البدائل بعد الدمج
هي `src/agent.py` للمحادثة و`src/assessment_agent.py` للتقييم.

## ماذا يقول مطور الـBackend للـFrontend لاحقًا؟

### بدء Free أو Guided

يرسل الباك إند الموثوق:

```http
POST /v1/practice-sessions
Authorization: Bearer <SERVICE_API_KEY>
Content-Type: application/json
```

مثال Free:

```json
{
  "user_id": "opaque-user-id",
  "participant_name": "Learner",
  "mode": "free"
}
```

مثال Guided:

```json
{
  "user_id": "opaque-user-id",
  "participant_name": "Learner",
  "mode": "guided",
  "scenario_id": "airport.check_in.a2",
  "placement_completed": true,
  "placement_level": "A2",
  "recording_consent": false
}
```

الاستجابة تعيد `participant_token` و`server_url` و`room_name` للاتصال بـLiveKit،
بالإضافة إلى `backend_session_id` الذي يربط جلسة المنتج بسجل محادثات الفريق.

في Guided يستمع الفرونت إند إلى topic باسم `guided.events` ويرسل أوامر
`retry`, `continue`, `replay`, `replay_slow`, `pause`, `resume`, `stop` عبر
`guided.command`. النصوص وتسلسل السيناريو يقررهما الباك إند، وليس الفرونت إند.

### التقييم الشفهي

يستدعي الباك إند الموثوق `POST /v1/assessment-sessions` مع `user_id` ولغة
الواجهة. تنشئ الاستجابة التقييم وتعيد token وغرفة LiveKit مخصصين للعامل
`english-level-assessor` و`assessment_id` و`result_url`. العامل يحصل على كل
سؤال من خدمة التقييم داخل التطبيق نفسه، ويرسل الأدلة إليها، ولا يحدد المستوى
محليًا.

### جلب النتائج

- نتيجة Free أو Guided:
  `GET /v1/practice-sessions/{practice_session_id}/result?mode=free|guided`
- نتيجة التقييم:
  `GET /v1/assessments/{assessment_id}/result`
- transcript وأحداث سجل الفريق:
  `GET /api/v1/sessions/{backend_session_id}/turns` و`/events`

## ما الذي يجب تشغيله؟

بعد تجهيز `.env.local` وتشغيل `scripts/setup.ps1`:

1. `scripts/run_api.ps1`
2. `scripts/run_tutor.ps1`
3. `scripts/run_assessor.ps1`

هذه ثلاث عمليات runtime، لكنها ليست ثلاثة backends: الأولى هي HTTP API،
والأخريان عاملا صوت يتصلان بـLiveKit. جميع البيانات الدائمة تعود إلى نفس
الباك إند ونفس قاعدة البيانات.

## حدود المسؤولية

- Django/الخدمة الأساسية تحتفظ بالمستخدمين والبيانات الشخصية وترسل معرّفًا
  غير حساس.
- FastAPI يملك العقود، إنشاء الجلسات، التقييم، السيناريوهات، النتائج، وسجل
  المحادثات.
- LiveKit يملك النقل اللحظي للصوت والـdata والـdispatch، وليس التخزين الدائم.
- الفرونت إند يعرض الحالة ويرسل الأوامر، ولا يقرر درجة أو انتقال سيناريو.
