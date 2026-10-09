# Telegram Bot Core — Phase 1

نواة عامة وقابلة لإعادة الاستخدام لبوتات Telegram مبنية على aiogram وPostgreSQL.
لا تحتوي هذه المرحلة على أي منطق مالي.

## الموجود حاليًا

- aiogram async بالكامل.
- asyncpg connection pool دائم.
- migrations بسيطة ومتسلسلة ومعزولة داخل PostgreSQL schema باسم `bot_core`.
- جدول مستخدمين أساسي فقط، بدون أرصدة، ولا يصطدم بجداول أي نسخة قديمة.
- Super Admin من `.env`.
- Fast callback acknowledgement لإزالة دائرة الانتظار قبل تنفيذ منطق الشاشة.
- قياس زمن معالجة التحديثات وتحذير عند البطء.
- فصل Router / Service / Repository.
- معالجة أخطاء مركزية.
- اسم البوت ديناميكي ولا توجد هوية بوت ثابتة داخل المشروع.

## التشغيل

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python -m app.main
```

## قواعد معمارية للمراحل التالية

1. الـhandlers لا تعدّل أي رصيد مباشرة.
2. كل منطق مالي سيكون داخل Service مستقل ومعاملة PostgreSQL صريحة.
3. قاعدة البيانات هي مصدر الحقيقة للحماية من الضغط المكرر والتزامن.
4. سرعة callback هي UX فقط ولا تُستخدم كحماية مالية.
5. لا نضيف أكثر من نطاق وظيفي واحد قبل اختباره ومراجعته.

## المرحلة التالية المقترحة

Wallet Core فقط: ledger + balances + holds + idempotency + invariants + tests، بدون أي مزود دفع خارجي.
