# Telegram Bot Core — Phase 2

نواة عامة وقابلة لإعادة الاستخدام لبوتات Telegram مبنية على aiogram وPostgreSQL.
هذه المرحلة تضيف **Wallet Core فقط** بدون شحن، سحب، مزودات خارجية أو أزرار مالية للمستخدم.

## النواة الموجودة

- aiogram async بالكامل.
- asyncpg connection pool دائم.
- migrations متسلسلة ومعزولة داخل PostgreSQL schema باسم `bot_core`.
- مستخدمون وصلاحية Super Admin.
- Fast callback acknowledgement وقياس latency.
- فصل Router / Service / Repository.
- اسم البوت ديناميكي ولا توجد هوية بوت ثابتة داخل المشروع.

## Wallet Core

- كل مبلغ مالي هو `BIGINT` بوحدة صحيحة فقط؛ `float` مرفوض من طبقة الخدمة.
- حساب مستقل حسب `telegram_id + asset_code + bucket`.
- `available` و`held` مع CHECK يمنع القيم السالبة.
- Ledger append-only مع before/delta/after ونسخة الحساب قبل/بعد.
- Idempotency key فريد لكل عملية ناجحة.
- نفس المفتاح مع نفس الطلب يعيد نفس نتيجة العملية ولا يكرر الحركة.
- نفس المفتاح مع طلب مختلف يسبب `IdempotencyConflict`.
- `SELECT ... FOR UPDATE` قبل أي قرار خصم أو حجز.
- Hold حقيقي: إنشاء، تحرير، أو Capture مرة واحدة فقط.
- قيود DB مؤجلة تتحقق عند COMMIT أن الرصيد يساوي مجموع الـledger.
- قيد DB إضافي يفرض أن `held` يساوي مجموع الـholds النشطة.
- Ledger وعمليات المحفظة غير قابلة للتعديل أو الحذف.
- لا يوجد API عام لتعيين الرصيد مباشرة؛ التغيير فقط credit/debit/hold/release/capture.

## مبدأ مهم

وجود `Wallet Core` لا يعني أننا فعّلنا أي عملية مالية للمستخدم. لا توجد حتى الآن أزرار شحن أو سحب، ولا أي API خارجي. المرحلة الحالية تبني مصدر الحقيقة المالي الذي ستستخدمه الأقسام اللاحقة.

## اختبار النواة المالية على بيئة الاختبار

بعد أن يرسل الأدمن `/start` للبوت، يمكن تشغيل اختبار صفري الرصيد على bucket منفصل اسمه `selftest`:

```bash
python -m scripts.wallet_selftest --telegram-id YOUR_TELEGRAM_ID
```

الاختبار يفحص idempotency والضغط المتزامن وحجز/تحرير الرصيد، ثم يعيد bucket الاختبار إلى صفر. لا يوجد زر Telegram ينفذ هذا الاختبار.

## فحص سلامة المحفظة

بعد إعداد `.env` يمكن تشغيل فحص قراءة فقط:

```bash
python -m scripts.wallet_audit
```

النتيجة السليمة:

```text
WALLET AUDIT: OK
```

## التشغيل

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python -m app.main
```

## قاعدة تطوير مالية

أي قسم مالي جديد يجب أن يستعمل `WalletService` ولا يكتب إلى `wallet_accounts` مباشرة. عمليات المزود الخارجي (شحن/سحب/iChancy) سيكون لها state machines مستقلة؛ Wallet Core لا يعيد إرسال أي طلب خارجي.
