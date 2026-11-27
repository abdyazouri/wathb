# توزيع نسخة التجربة الخاصة من تطبيق وَثْب (أندرويد)

نسخة التجربة لعدد محدود: منشأتان وخمسة عمال. تُوزَّع بطريقتين: Firebase App Distribution لمن عنده بريد إلكتروني، أو إرسال ملف الـ APK مباشرة عبر واتساب لمن ليس عنده. التطبيق يتصل بالسيرفر الحقيقي `https://wathb-api2.onrender.com/api/v1/`.

## بيانات النسخة الحالية

| البند | القيمة |
|---|---|
| معرّف التطبيق (applicationId) | `com.wathb.app` |
| versionName | `0.9.0-trial.2` |
| versionCode | `4` |
| أقل إصدار أندرويد (minSdk) | 26 (أندرويد 8) |
| targetSdk | 36 |

### بصمة شهادة التوقيع (SHA-256)

```
07:2E:A6:71:D3:AD:36:4A:9F:1E:85:78:1F:2E:68:34:3F:96:91:7B:D3:5F:94:1F:73:72:4D:6F:48:5D:78:42
```

هذه البصمة عامة ويمكن مشاركتها. تحقّق منها في أي ملف APK قبل توزيعه:

```
~/Library/Android/sdk/build-tools/36.0.0/apksigner verify --print-certs android/app/build/outputs/apk/release/app-release.apk
```

يجب أن يطابق سطر `Signer #1 certificate SHA-256 digest` البصمة أعلاه.

## مفتاح التوقيع

- المفتاح ملف keystore موجود خارج المستودع على جهاز المطوّر، والاسم المستعار (alias) فيه `wathb`.
- إعدادات التوقيع في الملف `android/keystore.properties`. هذا الملف **لا يُرفع إلى git أبدًا** (موجود في `.gitignore`)، ويحتوي على أربعة أسطر:

```
storeFile=/المسار/الكامل/إلى/wathb-release.jks
storePassword=...
keyAlias=wathb
keyPassword=...
```

- بدون هذا الملف تتوقف `assembleRelease` برسالة واضحة، أما نسخ الـ debug فتعمل عادي.
- **احفظ نسخة احتياطية** من ملف الـ keystore ومن كلمتي المرور في مكانين آمنين ومنفصلين. إذا ضاع المفتاح لا يمكن تحديث التطبيق عند المختبرين، وعليهم حذفه وتثبيته من جديد.

### إذا احتجت مفتاحًا جديدًا (جهاز جديد بلا مفتاح)

شغّل الأمر بنفسك في الطرفية (يطلب كلمتي مرور وبيانات الشهادة):

```
keytool -genkeypair -v -keystore ~/wathb-keys/wathb-release.jks -alias wathb -keyalg RSA -keysize 2048 -validity 10000
```

ثم اكتب `android/keystore.properties` كما في الأعلى. انتبه: المفتاح الجديد يعني بصمة جديدة، والمختبرون الذين ثبّتوا نسخة موقّعة بالمفتاح القديم يجب أن يحذفوها أولًا.

## البناء

```
cd android
./gradlew assembleRelease
```

الملف الناتج: `android/app/build/outputs/apk/release/app-release.apk`.

## التوزيع عبر Firebase App Distribution

التوزيع بأداة Firebase CLI فقط؛ التطبيق نفسه لا يحتوي على Firebase SDK ولا `google-services.json`.

### الإعداد لمرة واحدة

1. ثبّت الأداة: `npm install -g firebase-tools`
2. سجّل الدخول من المتصفح: `firebase login`
3. افتح https://console.firebase.google.com وأنشئ مشروعًا باسم **wathb** (أو اختره إن كان موجودًا). لا حاجة لـ Google Analytics.
4. داخل المشروع: **Add app ← Android**، واكتب اسم الحزمة `com.wathb.app`، ثم **Register app**. تخطَّ خطوات تنزيل `google-services.json` وإضافة الـ SDK؛ لا نحتاجها.
5. من **Project settings ← General ← Your apps** انسخ **App ID** (يبدأ بـ `1:` وينتهي بـ `:android:...`).
6. من القائمة الجانبية **Release & Monitor ← App Distribution ← Get started**، ثم تبويب **Testers & Groups ← Add group** باسم `trial` بالضبط، وأضف بريد كل مختبر داخل المجموعة. **لا تكتب بريد المختبرين في المستودع.**

### كل توزيع

1. ارفع `versionCode` بواحد في `android/app/build.gradle.kts` (وعدّل `versionName` مثل `0.9.0-trial.2`).
2. شغّل من جذر المستودع:

```
FIREBASE_APP_ID="<App ID من الخطوة 5>" scripts/distribute_trial.sh
```

يمكن تمرير ملاحظات الإصدار بالعربي كوسيط أول:

```
FIREBASE_APP_ID="..." scripts/distribute_trial.sh "إصلاح ظهور زر تأكيد الاستلام بعد الدفع."
```

السكربت يبني الـ APK الموقّع ويرسله لمجموعة `trial`، فيصل لكل مختبر بريد فيه رابط التنزيل.

## الإرسال المباشر عبر واتساب (لمن لا يملك بريدًا)

- أرسل الملف `android/app/build/outputs/apk/release/app-release.apk` **في محادثة خاصة** للمختبر.
- لا تنشره في مجموعة عامة ولا على الموقع. رابط التنزيل في صفحة الهبوط (`APK_URL`) يبقى فارغًا حتى نقرر الإطلاق العام.

## التثبيت عند المختبر

1. افتح رابط Firebase من البريد، أو افتح ملف الـ APK من واتساب.
2. إذا ظهر «للحماية، لا يُسمح بتثبيت تطبيقات من هذا المصدر»: اضغط **الإعدادات** وفعّل **السماح من هذا المصدر** (للمتصفح أو لواتساب أو لتطبيق Firebase App Tester)، ثم ارجع.
3. إذا ظهر تحذير **Play Protect** («تطبيق غير معروف»): اضغط **مزيد من التفاصيل ← التثبيت على أي حال**. التحذير طبيعي لأن التطبيق ليس من متجر Play.
4. على هواتف شاومي (HyperOS / MIUI) قد يُطلب تأكيد إضافي أو الانتظار بضع ثوانٍ قبل زر التثبيت.
5. افتح «وَثْب» وادخل برقم الهاتف وكلمة المرور.

## التحديث

- كل نسخة جديدة **بنفس المفتاح** و**versionCode أعلى** تُثبَّت فوق القديمة مباشرة، ويبقى المختبر داخل حسابه.
- إذا ثبّت المختبر نسخة موقّعة بمفتاح مختلف (مثل نسخة debug)، يجب حذفها أولًا ثم تثبيت النسخة التجريبية.
