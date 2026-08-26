# مستندات معماری و بازبینی فنی پروژه MidasScript

> **نسخه:** ۱.۰ — بر پایهٔ شاخهٔ `dev` در کامیت `73b73ca`
> **دامنه:** پکیج پایتونی `midas/`، رابط کاربری مرورگری `assets/`، و نقاط ورود ریشهٔ پروژه

---

## فهرست مطالب

1. [مروری کلی بر پروژه (Project Overview)](#۱-مروری-کلی-بر-پروژه-project-overview)
2. [ساختار کد و معماری (Code Structure & Architecture)](#۲-ساختار-کد-و-معماری-code-structure--architecture)
3. [اصول مهندسی نرم‌افزار در عمل (Software Principles in Action)](#۳-اصول-مهندسی-نرمافزار-در-عمل-software-principles-in-action)
4. [الگوهای طراحی به‌کاررفته (Design Patterns)](#۴-الگوهای-طراحی-بهکاررفته-design-patterns)
5. [راهبرد تست و تضمین صحت (Testing & Correctness Strategy)](#۵-راهبرد-تست-و-تضمین-صحت-testing--correctness-strategy)
6. [بازبینی انتقادی و نقاط قابل بهبود (Critical Review)](#۶-بازبینی-انتقادی-و-نقاط-قابل-بهبود-critical-review)
7. [پیوست: راهنمای اجرا (Appendix)](#۷-پیوست-راهنمای-اجرا-appendix)

---

## ۱. مروری کلی بر پروژه (Project Overview)

### ۱.۱. پروژه چیست؟

**MidasScript** یک ابزار کامل **بک‌تست (Backtesting)** و **بهینه‌سازی (Optimization)** برای یک استراتژی معاملاتی است. این پروژه، استراتژی‌ای که در اصل به زبان **Pine Script** (زبان پلتفرم TradingView) با نام «Ultimate script v0.3.7» نوشته شده بود را به پایتون **پورت (Port)** کرده و سه قابلیت اصلی روی آن ساخته است:

- **موتور بک‌تست رویدادمحور (Event-Driven Backtest Engine):** شبیه‌سازی دقیق اجرای استراتژی روی داده‌های تاریخی کندل‌های ۵ دقیقه‌ای طلا (XAU).
- **بهینه‌ساز پیش‌رو (Walk-Forward Optimizer):** یافتن پارامترهای بهینهٔ استراتژی با استفاده از کتابخانهٔ **Optuna** و روش **TPE**، به‌گونه‌ای که در برابر **بیش‌برازش (Overfitting)** مقاوم باشد.
- **نمایشگر مرورگری (Browser Viewer):** یک رابط کاربری تحت وب مبتنی بر کتابخانهٔ `lightweight-charts` برای مشاهدهٔ کندل‌ها، معاملات، منحنی سرمایه و آمار عملکرد.

### ۱.۲. هدف اصلی

هدف، پاسخ صادقانه به این پرسش است: **«آیا این استراتژی واقعاً لبهٔ آماری (Edge) دارد؟»**

نکتهٔ کلیدی طراحی این پروژه، **تعهد به صداقت آماری (Statistical Honesty)** است. چند تصمیم معماری مستقیماً از همین تعهد سرچشمه می‌گیرند:

- **مدل‌سازی هزینهٔ اسپرد (Spread):** قیمت هر کندل به‌عنوان قیمت میانی (Mid) در نظر گرفته می‌شود و هر پر شدن سفارش (Fill) به اندازهٔ نصف اسپرد به ضرر معامله جابه‌جا می‌شود؛ بنابراین هر رفت‌وبرگشت (Round-Turn) یک اسپرد کامل هزینه دارد.
- **قانون محافظه‌کارانهٔ پر شدن سفارش:** اگر در یک کندل هم حد ضرر (Stop-Loss) و هم حد سود (Take-Profit) لمس شوند، **حد ضرر اول** اجرا می‌شود.
- **مدیریت حفره‌های داده (Data Holes):** این مهم‌ترین مفهوم دامنه‌ای (Domain Concept) پروژه است و در بخش بعدی توضیح داده می‌شود.
- **توقف در ورشکستگی (Ruin Halt):** چون اندازهٔ پوزیشن به‌صورت هندسی (درصدی از سرمایهٔ زنده) محاسبه می‌شود، یک حساب بازنده هرگز دقیقاً به صفر نمی‌رسد بلکه بی‌نهایت به آن نزدیک می‌شود و معاملات بی‌معنی تولید می‌کند؛ به همین دلیل با افت سرمایه به زیر آستانهٔ مشخص، اجرا متوقف می‌شود.

### ۱.۳. مفهوم دامنه‌ای کلیدی: حفرهٔ داده در برابر تعطیلی بازار

فید دادهٔ خام، یک شبکهٔ پیوستهٔ ۵ دقیقه‌ای **نیست**. دو نوع شکاف زمانی وجود دارد که تفکیک آن‌ها حیاتی است:

| نوع شکاف | تعریف | رفتار درست |
| --- | --- | --- |
| **تعطیلی بازار (Market Closure)** | آخر هفته یا تعطیلات رسمی | خطا نیست. معامله‌گر واقعی هم پوزیشن را نگه می‌دارد و گپ روز دوشنبه را می‌پذیرد. |
| **حفرهٔ داده (Data Hole)** | بازهٔ طولانی‌تر از ۹۶ ساعت که کندل‌ها اساساً وجود ندارند | خطای داده است. نگه‌داشتن پوزیشن در این بازه، **داستان‌سرایی** است نه شبیه‌سازی. |

در دادهٔ فعلی چهار حفره وجود دارد که بزرگ‌ترین آن‌ها ۳۲ روز است (از ۲۰۲۵-۰۹-۱۲ تا ۲۰۲۵-۱۰-۱۵) و قیمت طلا در آن بازه ۱۴٫۷٪ بالاتر رفته است. پیش از رفع این مشکل، موتور بک‌تست پوزیشن را در سراسر این حفره «نگه می‌داشت» و حد ضرر یا حد سود روی کندل بازگشایی فعال می‌شد؛ یعنی یک جهش ۱۴٫۷ درصدی به‌عنوان یک معاملهٔ واقعی ثبت می‌شد. دو راهکار پیاده‌سازی شده است:

1. موتور، تمام پوزیشن‌های باز را در **بستهٔ آخرین کندل قبل از حفره** می‌بندد (با دلیل خروج `DataGap`) و برای تعداد مشخصی کندل پس از حفره، ورود جدید را مسدود می‌کند.
2. در **بازنمونه‌برداری (Resampling)** به تایم‌فریم‌های بالاتر، هیچ سطلی (Bucket) اجازهٔ عبور از یک حفره را ندارد. بنابراین نمودار روزانه نمی‌تواند ۲۰۲۵-۰۹-۱۲ را به ۲۰۲۵-۱۰-۱۵ بچسباند و یک کندل با دامنهٔ ۵۳۷ دلار بسازد.

### ۱.۴. جریان داده (Data Pipeline)

```
data.csv  (فایل خام CSV با جداکنندهٔ سمی‌کالن، ~۷۴ مگابایت)
    │
    ├── convert_csv.py ──►  5m_candles.json   (پاک‌سازی‌شده + گزارش یکپارچگی + لیست حفره‌ها)
    │
    ├── backtest.py    ──►  results.json              (آمار + تک‌تک معاملات + منحنی سرمایه)
    │                  ──►  5m_candles_chart.json     (برش کندل‌ها برای نمودار مرورگر)
    │
    ├── optimize.py    ──►  opt_results.json          (نتایج walk-forward)
    │
    └── serve.py       ──►  http://localhost:8765/    (سرو کردن index.html + API)
                                    │
                                    └──►  assets/js/main.js  (نمایشگر)
```

### ۱.۵. آمار کلی پروژه

| شاخص | مقدار |
| --- | --- |
| پکیج `midas/` | ۳٬۵۳۳ خط در ۳۵ ماژول |
| میانگین طول ماژول پکیج | حدود ۱۰۱ خط |
| بزرگ‌ترین ماژول پایتون | `midas/optimizer/walkforward.py` با ۲۷۹ خط |
| مجموع کد پایتون (با تست‌ها و نقاط ورود) | ۳٬۹۲۳ خط در ۴۱ فایل |
| کد جاوااسکریپت | ۱٬۷۲۱ خط در ۱۹ ماژول ES Module |
| تست واحد (Unit Test) | ۴۷ تست، بدون نیاز به فایل داده |
| نقاط ورود ریشه | ۵ اسکریپت، هرکدام ۱۰ تا ۱۱ خط |

---

## ۲. ساختار کد و معماری (Code Structure & Architecture)

### ۲.۱. معماری لایه‌ای (Layered Architecture)

معماری پروژه بر پایهٔ **معماری لایه‌ای (Layered Architecture)** و **قانون وابستگی (The Dependency Rule)** از **معماری تمیز (Clean Architecture)** بنا شده است. جهت وابستگی همیشه **یک‌طرفه** و رو به داخل است:

```
┌──────────────────────────────────────────────────────────────┐
│  midas/cli/          تحلیل آرگومان‌های خط فرمان                │
│  midas/server/       انتقال HTTP (مسیریابی، فایل ایستا)        │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  midas/app/          سناریوهای کاربرد (Use Cases)             │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  midas/optimizer/    فضای جست‌وجو، تابع هدف، walk-forward      │
│  midas/reporting/    خروجی ترمینال و فایل‌های JSON             │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  midas/engine/       سیگنال + پول ← معاملات، سرمایه، آمار      │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  midas/signals/      قیمت ← سیگنال ورود (بدون پول، بدون حالت)  │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  midas/data/         محور زمان: کندل‌ها، حفره‌ها، تایم‌فریم‌ها   │
│  midas/config/       دیتاکلاس پارامترها                       │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  midas/util/         توابع کمکی خالص، بدون دانش دامنه‌ای       │
└──────────────────────────────────────────────────────────────┘
```

#### دو ثابت معماری (Two Architectural Invariants)

این دو قانون، ستون فقرات معماری هستند و در **docstring** ماژول `midas/__init__.py` صریحاً مکتوب شده‌اند:

> **۱. هیچ چیز در لایه‌های زیر `midas/reporting/` چاپ نمی‌کند (`print` ندارد).**
> **۲. هیچ چیز در لایه‌های زیر `midas/server/` نمی‌داند که درخواست HTTP وجود دارد.**

قانون اول یک پیامد عملکردی مهم دارد: بهینه‌ساز که هزاران بار موتور را اجرا می‌کند، هزینهٔ ساخت رشته‌هایی که هرگز نمایش داده نمی‌شوند را نمی‌پردازد.

### ۲.۲. درخت دایرکتوری

```
Midas/
├── backtest.py             ◄── نقطهٔ ورود: اجرای یک بک‌تست
├── optimize.py             ◄── نقطهٔ ورود: بهینه‌سازی walk-forward
├── serve.py                ◄── نقطهٔ ورود: سرور محلی نمایشگر
├── convert_csv.py          ◄── نقطهٔ ورود: تبدیل CSV خام به JSON
├── timeframes.py           ◄── نقطهٔ ورود: گزارش یکپارچگی داده
├── index.html              ◄── نشانه‌گذاری (Markup) نمایشگر — فقط ساختار
├── MidasScript.pine        ◄── استراتژی اصلی Pine Script (مرجع صحت پورت)
├── bin/midas               ◄── اسکریپت bash برای اجرای سریع سرور
│
├── midas/                  ◄── پکیج اصلی پایتون
│   ├── __init__.py             تعریف لایه‌ها و دو ثابت معماری
│   ├── util/                   لایهٔ ۰ — توابع خالص
│   │   ├── timeutil.py             تبدیل epoch ↔ متن، تحلیل تاریخ
│   │   └── sampling.py             نازک‌سازی نقاط منحنی سرمایه
│   ├── config/
│   │   └── params.py               دیتاکلاس Params + تبدیل ورودی نامعتبر
│   ├── data/                   لایهٔ ۱ — محور زمان
│   │   ├── timeframes.py           تشخیص حفره + بازنمونه‌برداری
│   │   ├── series.py               شیء مقداری CandleSeries
│   │   └── csv_import.py           خواندن، پاک‌سازی و سریال‌سازی CSV
│   ├── signals/                لایهٔ ۲ — تولید سیگنال
│   │   ├── indicators.py           EMA، True Range، میانگین متحرک
│   │   ├── triggers.py             سه محرک ورود + کلاس پایه
│   │   └── generator.py            هماهنگ‌کنندهٔ تولید SignalSet
│   ├── engine/                 لایهٔ ۳ — موتور اجرا
│   │   ├── position.py             Position و Trade و ExitReason
│   │   ├── broker.py               Bar، Fill، SpreadModel، IntrabarBroker
│   │   ├── account.py              Account و DailyLossLimit
│   │   ├── gaps.py                 GapPolicy — سیاست حفره‌های داده
│   │   ├── observer.py             قرارداد ناظر اجرا (NullObserver)
│   │   ├── backtester.py           حلقهٔ اصلی کندل‌به‌کندل
│   │   └── statistics.py           محاسبهٔ شاخص‌های عملکرد
│   ├── reporting/              لایهٔ ۴ — خروجی
│   │   ├── ansi.py                 پالت رنگ ترمینال
│   │   ├── console.py              ConsoleObserver + خلاصهٔ پایانی
│   │   └── writers.py              نویسندهٔ فایل‌های JSON
│   ├── optimizer/              لایهٔ ۴ — بهینه‌سازی
│   │   ├── space.py                فضای جست‌وجوی پارامترها
│   │   ├── objective.py            تعریف «بهتر» + ارزیاب
│   │   ├── config.py               WalkForwardConfig
│   │   └── walkforward.py          چین‌بندی (Folds) و اجرای مطالعه
│   ├── server/                 لایهٔ ۵ — انتقال
│   │   ├── http.py                 Response، StaticFiles
│   │   ├── state.py                ViewerState، BackgroundJob
│   │   ├── api.py                  جدول مسیرها + هندلرها
│   │   └── app.py                  اتصال به BaseHTTPRequestHandler
│   ├── app/                    لایهٔ ۵ — سناریوهای کاربرد
│   │   ├── loading.py              بارگذاری سری با گزارش متنی
│   │   └── backtest_run.py         سناریوی «اجرا و ذخیرهٔ خروجی»
│   └── cli/                    لایهٔ ۶ — رابط خط فرمان
│       ├── backtest_cli.py
│       ├── optimize_cli.py
│       ├── serve_cli.py
│       ├── convert_cli.py
│       └── timeframes_cli.py
│
├── assets/                 ◄── رابط کاربری
│   ├── css/app.css             تمام ظاهر (Presentation)
│   └── js/
│       ├── core/               ابزارهای پایه
│       │   ├── format.js           قالب‌بندی عدد و تاریخ
│       │   ├── dom.js              کمک‌کننده‌های DOM + toast
│       │   └── bus.js              گذرگاه رویداد (Event Bus)
│       ├── data/
│       │   ├── api.js              تمام فراخوانی‌های سرور
│       │   └── store.js            وضعیت دادهٔ بارگذاری‌شده
│       ├── chart/              منطق نمودار
│       │   ├── timeframes.js       بازنمونه‌برداری در مرورگر (تابع خالص)
│       │   ├── smoothing.js        فیلتر Savitzky–Golay (تابع خالص)
│       │   ├── theme.js            رنگ‌ها و تنظیمات مشترک نمودار
│       │   ├── markers.js          نشانگرهای ورود/خروج/حفره
│       │   ├── tooltip.js          راهنمای شناور و لجند
│       │   ├── sizeCompare.js      پنل مقایسهٔ اندازهٔ کندل
│       │   └── chartView.js        کنترل‌کنندهٔ نمودار قیمت و سرمایه
│       ├── panels/             پنل‌های رابط کاربری
│       │   ├── header.js           نوار عنوان و چیپ‌های آماری
│       │   ├── stats.js            تب آمار
│       │   ├── trades.js           جدول معاملات
│       │   ├── monthly.js          مودال سود/زیان ماهانه
│       │   ├── settings.js         کشوی ویرایش پارامترها
│       │   └── optimizer.js        کشوی بهینه‌سازی
│       └── main.js             راه‌اندازی و سیم‌کشی
│
├── tests/
│   └── test_units.py           ۴۷ تست واحد
└── docs/
    └── ARCHITECTURE.fa.md      همین سند
```

### ۲.۳. شرح مسئولیت فایل‌های اصلی

#### نقاط ورود (Entry Points)

هر پنج اسکریپت ریشه، فقط یک **نما (Shim)** حدوداً ۱۰ خطی هستند. هدف، حفظ سازگاری با تمام دستورات مستندشده در `README.md` است، در حالی که منطق واقعی به پکیج منتقل شده است:

```python
# backtest.py — کل محتوای فایل
"""Entry point: `python3 backtest.py [options]`."""

from midas.cli.backtest_cli import main

if __name__ == "__main__":
    main()
```

#### `midas/config/params.py` — قرارداد پارامترها

یک **دیتاکلاس (dataclass)** با ۴۵ فیلد که تمام پارامترهای استراتژی را نگه می‌دارد: طول EMAها، آستانه‌های سه محرک، حد ضرر پویا، محدودیت زیان روزانه، فیلتر جلسهٔ معاملاتی، اسپرد و غیره.

مهم‌ترین بخش، متد `from_dict` است — **تنها نقطه‌ای در کل پروژه که ورودی نامعتمد (Untrusted Input) به یک شیء معتبر تبدیل می‌شود**:

```python
@classmethod
def from_dict(cls, values: dict | None, *, base: "Params" | None = None,
              strict: bool = False) -> "Params":
    """Copy `base` (defaults if omitted) with `values` applied on top."""
    params = replace(base) if base is not None else cls()
    for key, value in (values or {}).items():
        if not hasattr(params, key):
            continue                       # کلیدهای ناشناخته نادیده گرفته می‌شوند
        try:
            setattr(params, key, _cast_like(getattr(params, key), value))
        except (TypeError, ValueError) as exc:
            if strict:
                raise ParamError(f"bad value for {key}: {value!r}") from exc
    return params
```

پارامتر `strict` دو نیاز متفاوت را پوشش می‌دهد: سرور HTTP با `strict=True` فراخوانی می‌کند تا خطای ۴۰۰ به مرورگر برگرداند، اما بهینه‌ساز که ساعت‌ها اجرا می‌شود با حالت غیرسخت‌گیرانه کار می‌کند تا یک مقدار نامعتبر کل مطالعه را متوقف نکند.

#### `midas/data/series.py` — شیء مقداری `CandleSeries`

پیش از بازآرایی، هر تابع امضایی به شکل `(epoch, o, h, l, c, v, holes)` داشت و همین تاپل هفت‌تایی در سراسر پروژه دست‌به‌دست می‌شد. اکنون یک **شیء مقداری تغییرناپذیر (Immutable Value Object)** جای آن را گرفته است که می‌داند چگونه خودش را برش بزند و پنجره‌های زمانی‌اش را پیدا کند:

```python
@dataclass(frozen=True)
class CandleSeries:
    epoch: np.ndarray          # مهر زمانی باز شدن کندل، اکیداً صعودی
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    holes: list = field(default_factory=list)

    def window(self, start_ts=None, end_ts=None) -> tuple:
        """اندیس اولین و آخرین کندل برای بازهٔ زمانی [start, end]"""
        first = self.index_at(start_ts) if start_ts else 0
        last = self.index_at(end_ts, side="right") if end_ts else len(self)
        return first, max(last, first + 1)

    def slice(self, start: int, stop: int | None = None) -> "CandleSeries":
        """زیرسری، به‌همراه حفره‌های داده که روی آفست جدید بازاندیس شده‌اند"""
```

نکتهٔ ظریف در `slice`: بازاندیس‌گذاری حفره‌ها به‌طور خودکار انجام می‌شود. پیش‌تر، هر فراخوان‌کننده باید خودش این کار را به‌صورت درون‌خطی تکرار می‌کرد و فراموش کردن آن یک باگ خاموش تولید می‌کرد.

#### `midas/signals/` — تولید سیگنال خالص

این لایه **هیچ اطلاعی از پول ندارد**. ورودی: قیمت‌ها و پارامترها. خروجی: یک `SignalSet` که برای هر کندل مشخص می‌کند آیا ورود باید انجام شود، در چه جهتی، با چه حد ضرر و حد سودی.

- **`indicators.py`** — اولیه‌های عددی محض: `ema`، `true_range`، `rolling_mean_prev`، `shift`، `clock`، `day_of_month`. هر تابع دقیقاً معادل یک تابع داخلی Pine است تا صحت پورت خط‌به‌خط قابل بررسی باشد.
- **`triggers.py`** — سه محرک ورود به شکل سه کلاس با یک کلاس پایهٔ مشترک.
- **`generator.py`** — تابع `compute_signals` که مراحل را به ترتیب هماهنگ می‌کند: ساخت ویژگی‌های کندل ← فیلتر روند ← اجرای محرک‌ها ← تجمیع بر اساس اولویت ← حد ضرر پویا ← محاسبهٔ حد سود ← فیلترهای زمانی.

#### `midas/engine/` — موتور اجرا

قلب پروژه. مسئولیت‌ها به‌دقت تفکیک شده‌اند:

| فایل | مسئولیت |
| --- | --- |
| `position.py` | یک پوزیشن باز (`Position`) و رکورد معاملهٔ بسته‌شده (`Trade`) و `ExitReason` |
| `broker.py` | «چه قیمتی پر می‌شود» و «کدام سفارش زودتر فعال می‌شود» |
| `account.py` | پول: سود محقق‌شده، منحنی سرمایه، محاسبهٔ حجم، و ماشین حالت محدودیت زیان روزانه |
| `gaps.py` | سیاست معامله در اطراف حفره‌های داده |
| `observer.py` | قرارداد گزارش رویداد به دنیای بیرون |
| `backtester.py` | حلقهٔ اصلی — فقط هماهنگی، بدون قانون |
| `statistics.py` | تبدیل معاملات به شاخص‌های عملکرد |

حلقهٔ اصلی در `backtester.py` عمداً به فهرستی از دغدغه‌های شماره‌گذاری‌شده تبدیل شده که هرکدام یک خط هستند؛ قانون پشت هر خط در ماژول خودش زندگی می‌کند:

```python
for i in range(first, last):
    bar = Bar(i, int(series.epoch[i]), series.open[i], series.high[i],
              series.low[i], series.close[i])

    year_marker = self._maybe_mark_year(bar, year_marker, open_positions, account)

    # ۱) کارگزار: خروج حد ضرر/حد سود درون‌کندلی برای پوزیشن‌های قبلی
    open_positions = self._resolve_exits(open_positions, bar, account)

    # ۲) رویدادهای بستن همه، هرکدام در بستهٔ همین کندل
    for triggered, reason in (
            (signals.trend_changed[i], ExitReason.TREND_CHANGE),
            (signals.is_close_time[i], ExitReason.TIME_EXIT),
            (gaps.flatten_at(i), ExitReason.DATA_GAP)):
        if open_positions and triggered:
            self._close_all(open_positions, bar, account, reason)
            open_positions = []

    # ۳) سرمایهٔ زنده، شامل سود شناور
    equity = account.equity_with(open_positions, bar.close)

    # ۴) توقف ورشکستگی
    if equity <= account.initial * self.settings.ruin_floor:
        ...
```

#### `midas/server/` — انتقال HTTP

چهار ماژول با مرزهای روشن:

- **`http.py`** — شیء `Response` و کلاس `StaticFiles` که فایل‌های ایستا را سرو می‌کند و از **پیمایش مسیر (Path Traversal)** جلوگیری می‌کند.
- **`state.py`** — `ViewerState` (سری کندل که یک‌بار در حافظه بارگذاری می‌شود) و `BackgroundJob` (اجرای بهینه‌سازی در ترد پس‌زمینه با گزارش پیشرفت).
- **`api.py`** — کلاس `ViewerApi` که مسیرها را در یک دیکشنری اعلام می‌کند.
- **`app.py`** — تنها جایی که `BaseHTTPRequestHandler` را می‌شناسد؛ صرفاً مکانیک پروتکل.

```python
self.routes = {
    ("GET",  "/api/last"):              self.last_stats,
    ("GET",  "/api/defaults"):          self.defaults,
    ("GET",  "/api/optimize/status"):   self.optimization_status,
    ("POST", "/api/run"):               self.run,
    ("POST", "/api/optimize/estimate"): self.estimate_optimization,
    ("POST", "/api/optimize/start"):    self.start_optimization,
}
```

#### `midas/app/` — سناریوهای کاربرد

مرز میان موتور خالص و دنیای بیرون. تابع `run_backtest` دقیقاً همان دنبالهٔ کاری است که **هم خط فرمان و هم سرور HTTP** به آن نیاز دارند؛ بنابراین یک‌بار نوشته شده است:

```python
def run_backtest(series, params, execution: ExecutionSettings,
                 outputs: OutputSettings | None = None,
                 observer=None, announce=print) -> dict:
    """اجرا، خلاصه‌سازی و نوشتن results.json و برش نمودار."""
    result = Backtester(params, execution, observer).run(series)
    stats = statistics_for(result, series.epoch)
    ...
```

#### رابط کاربری (`index.html` + `assets/`)

پیش‌تر کل نمایشگر یک فایل `index.html` با ۱٬۵۶۲ خط بود که CSS، HTML و حدود ۱٬۰۸۸ خط جاوااسکریپت را در خود جای داده بود. اکنون:

- **`index.html`** (۲۵۵ خط) فقط نشانه‌گذاری است.
- **`assets/css/app.css`** تمام ظاهر را در بر دارد.
- **`assets/js/`** به ۱۹ ماژول ES تقسیم شده که از طریق یک **گذرگاه رویداد (Event Bus)** با هم صحبت می‌کنند.

---

## ۳. اصول مهندسی نرم‌افزار در عمل (Software Principles in Action)

### ۳.۱. اصل تک‌مسئولیتی — Single Responsibility Principle (SRP)

> **تعریف:** هر ماژول یا کلاس باید تنها **یک دلیل برای تغییر** داشته باشد. مسئولیت‌های متفاوت که به دلایل متفاوت تغییر می‌کنند، باید در واحدهای جداگانه قرار بگیرند.

**شواهد در پروژه:**

فایل `backtest.py` پیش از بازآرایی **۷۶۵ خط** بود و هم‌زمان شش مسئولیت داشت: رنگ‌های ترمینال، بارگذاری داده، موتور اجرا، محاسبهٔ آمار، نوشتن فایل‌های خروجی، و تحلیل آرگومان‌های خط فرمان. هر یک از این‌ها به دلیل کاملاً متفاوتی تغییر می‌کنند.

اکنون این فایل به هشت ماژول تقسیم شده است:

| مسئولیت | مقصد جدید | خطوط |
| --- | --- | --- |
| رنگ ترمینال | `midas/reporting/ansi.py` | ۳۲ |
| بارگذاری داده | `midas/data/series.py` + `midas/app/loading.py` | ۱۱۶ + ۳۰ |
| قوانین پر شدن سفارش | `midas/engine/broker.py` | ۷۶ |
| پول و محدودیت زیان | `midas/engine/account.py` | ۶۵ |
| سیاست حفرهٔ داده | `midas/engine/gaps.py` | ۴۳ |
| حلقهٔ اجرا | `midas/engine/backtester.py` | ۲۴۶ |
| آمار | `midas/engine/statistics.py` | ۱۶۵ |
| نوشتن JSON | `midas/reporting/writers.py` | ۱۲۸ |
| خط فرمان | `midas/cli/backtest_cli.py` | ۹۲ |

به همین ترتیب، تابع `compute_signals` که **۱۸۰ خط** بود، به `indicators.py` + سه کلاس محرک + یک هماهنگ‌کننده تقسیم شد.

**نمونهٔ ظریف‌تر:** پیش‌تر، موتور بک‌تست خودش تصمیم می‌گرفت که «هر چند معامله یک‌بار چاپ شود» (`print_every`) و «آیا حالت ساکت فعال است» (`quiet`). این‌ها دغدغهٔ **نمایش** هستند، نه دغدغهٔ **شبیه‌سازی**. اکنون این دو تنظیم در `ConsoleObserver` زندگی می‌کنند و موتور اصلاً از وجودشان بی‌خبر است.

### ۳.۲. اصل باز-بسته — Open/Closed Principle (OCP)

> **تعریف:** موجودیت‌های نرم‌افزاری باید **برای گسترش باز** و **برای تغییر بسته** باشند؛ یعنی افزودن رفتار جدید نباید مستلزم دست‌کاری کد موجود و آزموده باشد.

**شواهد ۱ — محرک‌های ورود:**

سه محرک ورود، از یک کلاس پایهٔ مشترک ارث می‌برند و در یک تابع کارخانه‌ای فهرست می‌شوند:

```python
def triggers_from_params(params) -> list:
    """محرک‌ها به ترتیب اولویت — اولین محرکی که روی یک کندل فعال شود، برنده است."""
    return [
        EngulfingBigCandle(params, "t3"),
        SingleBigCandle(params, "t1"),
        ConsecutiveCandles(params, "t2"),
    ]
```

منطق تجمیع (`_consolidate` در `generator.py`) صرفاً روی این فهرست پیمایش می‌کند:

```python
for trigger in triggers:
    detection = trigger.detect(context)
    for mask, direction in ((detection.bull, 1), (detection.bear, -1)):
        claim = mask & (entries.reason == REASON_NONE)
        entries.direction[claim] = direction
        entries.reason[claim] = trigger.code
        ...
```

**نتیجه:** افزودن یک محرک چهارم = نوشتن یک کلاس جدید + افزودن یک سطر به فهرست بالا. نه منطق تجمیع، نه ریاضیات حد ضرر و حد سود، و نه موتور بک‌تست هیچ‌کدام تغییر نمی‌کنند.

**شواهد ۲ — مسیرهای API:** افزودن یک نقطهٔ پایانی جدید، یک سطر در دیکشنری `self.routes` است. متد `handle` هرگز تغییر نمی‌کند.

**شواهد ۳ — تابع هدف بهینه‌سازی:** معیار بهینه‌سازی (Sharpe، Sortino، Calmar) یک فیلد در دیتاکلاس `Objective` است، نه یک زنجیرهٔ `if/elif` در حلقهٔ بهینه‌سازی.

### ۳.۳. اصل جایگزینی لیسکوف — Liskov Substitution Principle (LSP)

> **تعریف:** اشیای یک نوع باید بتوانند بدون شکستن صحت برنامه، با اشیای زیرنوع خود جایگزین شوند. هر پیاده‌سازی از یک قرارداد باید در تمام جایگاه‌های آن قرارداد قابل استفاده باشد.

**شواهد:**

`Backtester` هرگز نوع ناظر (Observer) خود را بررسی نمی‌کند. دو پیاده‌سازی وجود دارد و هر دو کاملاً قابل تعویض‌اند:

```python
# در بهینه‌ساز — سکوت مطلق، بدون هزینهٔ ساخت رشته
result = Backtester(params, settings).run(self.series)     # پیش‌فرض: NullObserver

# در خط فرمان — گزارش کامل زنده
Backtester(params, execution, ConsoleObserver(print_every=1)).run(series)
```

همین الگو برای `IntrabarBroker` نیز برقرار است: سازندهٔ `Backtester` آن را به‌صورت **تزریق وابستگی (Dependency Injection)** می‌پذیرد، بنابراین می‌توان یک کارگزار با قوانین متفاوت (مثلاً «حد سود اول») جایگزین کرد بدون آنکه حلقهٔ اجرا بداند:

```python
def __init__(self, params, settings=None, observer=None, broker=None):
    self.broker = broker or IntrabarBroker()
```

### ۳.۴. اصل تفکیک واسط — Interface Segregation Principle (ISP)

> **تعریف:** هیچ مصرف‌کننده‌ای نباید مجبور به وابستگی به متدهایی شود که استفاده نمی‌کند. واسط‌های بزرگ و همه‌کاره باید به واسط‌های کوچک و متمرکز شکسته شوند.

**شواهد:**

قرارداد ناظر، به‌جای یک متد بزرگ `log(event_type, **kwargs)`، به ده قلاب (Hook) ریزدانه شکسته شده که هرکدام دقیقاً یک رویداد را توصیف می‌کنند:

```python
class NullObserver:
    def signals_started(self): pass
    def signals_ready(self, entry_count, seconds): pass
    def window_selected(self, first, last, start_ts, end_ts): pass
    def gap_policy(self, hole_count, warmup_bars): pass
    def run_started(self, capital, bars): pass
    def year_started(self, timestamp, open_positions, closed_trades, equity): pass
    def position_opened(self, position): pass
    def position_closed(self, trade): pass
    def account_ruined(self, timestamp, trades, equity, floor_fraction): pass
    def run_finished(self, seconds, trades, equity): pass
```

هر ناظر می‌تواند فقط رویدادهای موردنیازش را معنادار پیاده‌سازی کند. برای نمونه `ConsoleObserver` تفاوت قائل می‌شود میان رویدادهای «قاب‌بندی» (که با `--quiet` هم نمایش داده می‌شوند) و رویدادهای «گزارش زنده» (که با `--quiet` حذف می‌شوند).

همچنین لایهٔ `midas/app/` دقیقاً یک تابع در معرض دید قرار می‌دهد (`run_backtest`)؛ سرور HTTP نیازی به شناخت `Backtester`، `Account` یا `GapPolicy` ندارد.

### ۳.۵. اصل وارونگی وابستگی — Dependency Inversion Principle (DIP)

> **تعریف:** ماژول‌های سطح‌بالا نباید به ماژول‌های سطح‌پایین وابسته باشند؛ هر دو باید به **انتزاع (Abstraction)** وابسته باشند. همچنین، انتزاع باید متعلق به مصرف‌کننده باشد، نه پیاده‌ساز.

**شواهد — کلاسیک‌ترین نمونه در این پروژه:**

پیش از بازآرایی، موتور بک‌تست مستقیماً `print` صدا می‌زد؛ یعنی یک ماژول سطح‌بالا (منطق کسب‌وکار) به یک جزئیات سطح‌پایین (ترمینال) وابسته بود.

اکنون:

1. قرارداد ناظر در `midas/engine/observer.py` تعریف شده — یعنی **در لایهٔ مصرف‌کننده**، نه در لایهٔ گزارش‌دهی. این دقیقاً همان چیزی است که DIP می‌خواهد: انتزاع متعلق به کسی است که از آن استفاده می‌کند.
2. موتور فقط رویداد منتشر می‌کند:

```python
self.observer.position_opened(position)
self.observer.account_ruined(bar.time, ruin.trades, equity, self.settings.ruin_floor)
```

3. `midas/reporting/console.py` این قرارداد را پیاده‌سازی می‌کند — یعنی **لایهٔ پایین‌تر به بالاتر وابسته است**، و جهت وابستگی وارونه شده است.

**پیامد عملکردی:** بهینه‌ساز که برای هر مطالعه هزاران بک‌تست اجرا می‌کند، `NullObserver` را پاس می‌دهد و هزینهٔ ساخت رشته‌های قالب‌بندی‌شده‌ای که هرگز چاپ نمی‌شوند را نمی‌پردازد.

### ۳.۶. اصل عدم تکرار — Don't Repeat Yourself (DRY)

> **تعریف:** هر تکه از دانش باید یک نمایش **واحد، بدون ابهام و معتبر** در سیستم داشته باشد. تکرار منطق یعنی هر تغییر باید در چند جا اعمال شود و فراموشی یکی از آن‌ها یک باگ است.

**شواهد — پنج مورد تکرار حذف‌شده:**

| دانش تکراری | وضعیت قبل | وضعیت فعلی |
| --- | --- | --- |
| تبدیل نوع پارامترهای ورودی | حلقهٔ یکسان در `serve.py` و `optimize.py` | `Params.from_dict()` |
| قالب‌بندی مهر زمانی | سه کپی: `ts_str`، `_ts`، `ts_to_str` | `midas/util/timeutil.py` |
| نازک‌سازی منحنی سرمایه | دو کپی در `backtest.py` و `optimize.py` | `midas/util/sampling.py` |
| قوانین پر شدن سفارش | دو شاخهٔ مجزا برای خرید و فروش | یک قانون بر پایهٔ علامت جهت |
| آزمون «کندل بزرگ» | دوبار برای محرک‌های ۱ و ۳ | تابع `big_candle_masks` |
| مرزبندی سطل تایم‌فریم | دوبار در `resample` و `resample_line` | تابع `_bucket_edges` |

**نمونهٔ شاخص — یکسان‌سازی منطق خرید و فروش:**

پیش‌تر قوانین خروج درون‌کندلی، دوبار نوشته شده بودند؛ یک‌بار برای پوزیشن خرید و یک‌بار به‌صورت آینه‌ای برای فروش (حدود ۲۰ خط تکراری در وسط حلقهٔ اصلی). اکنون با ضرب در علامت جهت، یک‌بار نوشته می‌شود:

```python
def resolve(self, position: Position, bar: Bar) -> Fill | None:
    direction = position.direction
    if direction * (bar.open - position.stop_loss) <= 0:
        return Fill(bar.open, ExitReason.STOP_LOSS)      # گپ از روی حد ضرر
    if direction * (bar.open - position.take_profit) >= 0:
        return Fill(bar.open, ExitReason.TAKE_PROFIT)    # گپ از روی حد سود
    if direction * (bar.adverse(direction) - position.stop_loss) <= 0:
        return Fill(position.stop_loss, ExitReason.STOP_LOSS)
    if direction * (bar.favourable(direction) - position.take_profit) >= 0:
        return Fill(position.take_profit, ExitReason.TAKE_PROFIT)
    return None
```

مفاهیم «بدترین قیمت» و «بهترین قیمت» به خود `Bar` منتقل شده‌اند:

```python
def adverse(self, direction: int) -> float:
    """قیمت حدی‌ای که به پوزیشن در این جهت آسیب می‌زند."""
    return self.low if direction == 1 else self.high
```

**نمونهٔ دوم — نگاشت نام‌ها به‌جای زنجیرهٔ انتساب:** در بهینه‌ساز، تمام نام‌های پیشنهادی Optuna عمداً دقیقاً برابر نام فیلدهای `Params` انتخاب شده‌اند، به‌جز دو مورد. بنابراین به‌جای ۲۰ خط انتساب دستی، فقط یک نگاشت کوچک و یک فراخوانی لازم است:

```python
FIELD_ALIASES = {"ema_fast": "ema_fast_len", "ema_slow": "ema_slow_len"}

def build_params(values: dict, base=None, groups=None) -> Params:
    renamed = {FIELD_ALIASES.get(k, k): v for k, v in (values or {}).items()}
    params = Params.from_dict(renamed, base=base)
    ...
```

### ۳.۷. تفکیک دغدغه‌ها — Separation of Concerns (SoC)

> **تعریف:** برنامه باید به بخش‌های مجزا تقسیم شود که هرکدام یک دغدغهٔ متمایز را پوشش می‌دهند و هم‌پوشانی حداقلی داشته باشند.

**شواهد ۱ — سمت بک‌اند:** دو ثابت معماری که پیش‌تر ذکر شد (`print` فقط در `reporting`، و HTTP فقط در `server`) دقیقاً مصداق SoC هستند.

**شواهد ۲ — سمت فرانت‌اند:** فایل ۱٬۵۶۲ خطی `index.html` سه دغدغهٔ کاملاً متفاوت را در هم آمیخته بود: ساختار، ظاهر و رفتار. اکنون:

- **ساختار (Structure):** `index.html` — ۲۵۵ خط، فقط نشانه‌گذاری. تنها دو ویژگی `style` باقی مانده که وضعیت نمایش اولیه را تعیین می‌کنند.
- **ظاهر (Presentation):** `assets/css/app.css` — ۲۳۵ خط. حتی سبک‌های درون‌خطی دکمه‌ها به کلاس تبدیل شدند (`.edit-btn.monthly`، `.icon-btn`).
- **رفتار (Behaviour):** ۱۹ ماژول ES در چهار گروه — `core/` (ابزار)، `data/` (وضعیت و ارتباط با سرور)، `chart/` و `panels/` (نما).

**شواهد ۳ — توابع خالص جدا از توابع دارای اثر جانبی:** منطق محاسباتی فرانت‌اند از منطق DOM جدا شده است. برای نمونه `assets/js/chart/timeframes.js` و `smoothing.js` **تابع خالص (Pure Function)** هستند: ورودی می‌گیرند، خروجی برمی‌گردانند و به DOM دست نمی‌زنند. این باعث می‌شود بتوان بازنمونه‌برداری در مرورگر را مستقل از نمودار آزمود.

### ۳.۸. قانون دیمیتر — Law of Demeter (LoD)

> **تعریف:** هر واحد باید فقط با «دوستان نزدیک» خود صحبت کند. یک شیء نباید ساختار درونی اشیای دیگر را بشکافد و از طریق زنجیرهٔ `a.b.c.d` به داده دست پیدا کند. به این اصل «اصل کمترین دانش (Principle of Least Knowledge)» هم گفته می‌شود.

**شواهد ۱ — پایان تاپل هفت‌تایی:**

```python
# قبل — هر تابع، هفت مقدار را باز و بسته می‌کرد
def run(epoch, o, h, l, c, v, params, capital, print_every=1, quiet=False,
        ruin_floor=0.01, start_ts=None, end_ts=None, log=True,
        holes=None, gap_flat=True, gap_warmup=0):
    i_start = int(np.searchsorted(epoch, start_ts)) if start_ts else 0
    i_end = int(np.searchsorted(epoch, end_ts, side="right")) if end_ts else n

# بعد — از شیء سؤال می‌پرسیم
def run(self, series) -> BacktestResult:
    first, last = series.window(self.settings.start_ts, self.settings.end_ts)
```

**شواهد ۲ — پایان کندوکاو در دیکشنری:** پوزیشن‌ها پیش‌تر دیکشنری بودند و حلقهٔ اصلی مستقیماً درونشان را می‌خواند:

```python
# قبل
open_profit = 0.0
for p in positions:
    open_profit += p["dir"] * (ci - p["entry_price"]) * p["qty"]
equity = initial + realized + open_profit

# بعد — پوزیشن خودش سود شناورش را می‌داند، و حساب، جمعش را
equity = account.equity_with(open_positions, bar.close)
```

که در `Account` چنین پیاده شده است:

```python
def equity_with(self, open_positions, price: float) -> float:
    """سرمایهٔ زنده: محقق‌شده به‌علاوهٔ سود شناور آنچه هنوز باز است."""
    return self.realized_equity + sum(p.unrealized(price) for p in open_positions)
```

**شواهد ۳ — پایان بازگشت تاپل هفت‌تایی:** تابع `run` پیش‌تر `(closed, equity_points, initial, realized, ruin_info, i_start, i_end)` برمی‌گرداند و هر فراخوان‌کننده باید ترتیب را حفظ می‌کرد. اکنون یک `BacktestResult` با فیلدهای نام‌دار برمی‌گردد.

**شواهد ۴ — گروه‌بندی پارامترها:** تابعی با ۱۴ آرگومان به یک دیتاکلاس `ExecutionSettings` تبدیل شد. این تکنیک در بازآرایی، **«معرفی شیء پارامتر» (Introduce Parameter Object)** نامیده می‌شود:

```python
@dataclass(frozen=True)
class ExecutionSettings:
    capital: float = 10000.0
    start_ts: int | None = None
    end_ts: int | None = None
    ruin_floor: float = 0.01
    flatten_before_gaps: bool = True
    gap_warmup_bars: int = 0
```

### ۳.۹. رفع وسواس نوع اولیه — Primitive Obsession Removal

> **تعریف:** «وسواس نوع اولیه» یک **بوی بد کد (Code Smell)** است که در آن مفاهیم دامنه‌ای با انواع اولیه (رشته، عدد، دیکشنری، تاپل) نمایش داده می‌شوند، به‌جای آنکه نوع اختصاصی خود را داشته باشند.

**شواهد — اشیای مقداری معرفی‌شده:**

| مفهوم دامنه‌ای | نمایش قبلی | نوع فعلی |
| --- | --- | --- |
| سری کندل | تاپل ۷ عضوی | `CandleSeries` |
| پوزیشن باز | `dict` با ۱۲ کلید | `Position` (با `slots`) |
| معاملهٔ بسته‌شده | `dict` | `Trade` با متد `as_dict()` |
| نتیجهٔ اجرا | تاپل ۷ عضوی | `BacktestResult` |
| تنظیمات اجرا | ۱۴ آرگومان مجزا | `ExecutionSettings` |
| پر شدن سفارش | تاپل `(price, reason)` | `Fill` |
| یک کندل | ۵ متغیر محلی | `Bar` |
| پیکربندی بهینه‌سازی | `dict` با ۱۵ کلید | `WalkForwardConfig` |
| پاسخ HTTP | تاپل `(code, body, ctype)` | `Response` |

نکتهٔ مهم: `Trade.as_dict()` مرز میان **مدل داخلی** و **قالب سیمی (Wire Format)** را حفظ می‌کند. مدل داخلی می‌تواند تغییر کند بدون آنکه ساختار `results.json` که مرورگر می‌خواند بشکند.

### ۳.۱۰. تغییرناپذیری — Immutability

> **تعریف:** شیء تغییرناپذیر پس از ساخته شدن قابل تغییر نیست. این ویژگی، دسته‌ای کامل از باگ‌ها (تغییر غیرمنتظره از راه دور — Action at a Distance) را حذف می‌کند.

**شواهد:** تمام اشیای مقداری با `@dataclass(frozen=True)` تعریف شده‌اند: `CandleSeries`، `ExecutionSettings`، `BacktestResult`، `Bar`، `Fill`، `Response`، `WalkForwardConfig`، `Objective`، `BarFeatures`، `TriggerContext`، `Detection`.

نمونهٔ عملی از اهمیت این موضوع در بهینه‌ساز:

```python
def _params_from(self, values) -> Params:
    # کپی تازه از پارامترهای پایه در هر بار، تا تغییرات یک آزمون
    # هرگز به آزمون بعدی نشت نکند
    base = Params.from_dict(self.config.base_params)
    return build_params(values, base=base, groups=self.config.groups)
```

### ۳.۱۱. شکست سریع — Fail Fast

> **تعریف:** سیستم باید خطاها را در نزدیک‌ترین نقطه به منشأ آن‌ها و با صریح‌ترین پیام ممکن آشکار کند، به‌جای آنکه با داده‌های نامعتبر به کار ادامه دهد و نتایج بی‌معنی تولید کند.

**شواهد:**

```python
if not series.strictly_increasing():
    raise DataError(
        f"{path}: timestamps are not strictly increasing (duplicate or "
        f"out-of-order bars). Re-run `python3 convert_csv.py`, which "
        f"sorts and de-duplicates the source CSV.")
```

این تصمیم مستقیماً از فلسفهٔ پروژه می‌آید: «یک بک‌تست فقط به اندازهٔ محور زمانش صادق است.» سری‌ای که مرتب نیست یا کندل تکراری دارد، **رد می‌شود** نه آنکه بی‌سروصدا اعداد تولید کند. پیام خطا حتی راه‌حل را هم پیشنهاد می‌دهد.

نمونه‌های دیگر: `make_folds` برای تعداد بخش کمتر از ۲ یا بازهٔ زمانی خالی، استثنا پرتاب می‌کند؛ و `ParamError` در حالت سخت‌گیرانه.

### ۳.۱۲. کد خودتوصیف و مستندسازی «چرا» — Self-Documenting Code

> **تعریف:** نام‌ها باید قصد را آشکار کنند و توضیحات باید به‌جای تکرار «چه کاری» انجام می‌شود، **«چرا»** را توضیح دهند.

**شواهد:** توضیحات این پروژه به‌طور نظام‌مند دلیل تصمیم‌ها را ثبت می‌کنند، نه مکانیک آن‌ها را:

```python
# The range is set in BAR INDICES, not timestamps: the time scale is
# index-based (it closes weekend and holiday gaps), so a timestamp range
# does not map to the span you expect — and a 5-minute trade asked for in
# seconds is invisible once the chart is on 1D.
```

```python
"""Why a cap: with geometric sizing and pyramiding, returns compound
explosively, so even ratio objectives drift toward near-ruin configurations.
Constraining MaxDD <= `dd_cap` and maximising the ratio *within* that
feasible region is the standard risk-controlled approach."""
```

همچنین نام‌گذاری از اختصارات به سمت وضوح حرکت کرده است: `sma_prev` → `rolling_mean_prev`، `_shift` → `shift`، `sl`/`tp` → `stop_loss`/`take_profit`، `wr()` → `win_rate()`.

---

## ۴. الگوهای طراحی به‌کاررفته (Design Patterns)

### ۴.۱. الگوی ناظر — Observer Pattern

> **تعریف:** یک شیء (Subject) فهرستی از وابستگان (Observers) نگه می‌دارد و در صورت تغییر وضعیت، به‌طور خودکار آن‌ها را مطلع می‌کند.

در `midas/engine/` موتور، رویدادها را منتشر می‌کند و `ConsoleObserver` آن‌ها را رندر می‌کند. اینجا از **تایپ اردکی (Duck Typing)** استفاده شده است — کلاس پایه‌ای برای ارث‌بری وجود ندارد و هر شیئی با این مجموعه متد کار می‌کند.

### ۴.۲. الگوی شیء تهی — Null Object Pattern

> **تعریف:** به‌جای بازگرداندن `null` و مجبور کردن مصرف‌کننده به بررسی مداوم، شیئی با رفتار خنثی ارائه می‌شود.

`NullObserver` دقیقاً این نقش را دارد. موتور هرگز مجبور نیست بنویسد `if self.observer is not None:` — یک شرط که در حلقه‌ای با میلیون‌ها تکرار اجرا می‌شد.

```python
self.observer = observer or NullObserver()
```

### ۴.۳. الگوی روش قالبی — Template Method Pattern

> **تعریف:** کلاس پایه اسکلت الگوریتم را تعریف می‌کند و گام‌های خاص را به زیرکلاس‌ها واگذار می‌کند.

کلاس `Trigger` متد عمومی `detect` را نهایی می‌کند (شامل بررسی فعال بودن محرک) و جزئیات تشخیص را به `_detect` در زیرکلاس‌ها می‌سپارد:

```python
def detect(self, context: TriggerContext) -> Detection:
    detection = self._detect(context)
    if self.enabled:
        return detection
    off = np.zeros(context.bars.count, dtype=bool)
    return Detection(off, off, detection.stop, detection.avg_body)

def _detect(self, context: TriggerContext) -> Detection:
    raise NotImplementedError
```

### ۴.۴. الگوی استراتژی — Strategy Pattern

> **تعریف:** خانواده‌ای از الگوریتم‌ها تعریف، کپسوله و قابل تعویض می‌شوند.

سه نمونه: `IntrabarBroker` (قوانین پر شدن سفارش)، `SpreadModel` (مدل هزینه)، و `Objective` (معیار بهینه‌سازی).

### ۴.۵. الگوی نما — Facade Pattern

> **تعریف:** یک واسط ساده در برابر زیرسیستمی پیچیده قرار می‌گیرد.

`midas/app/backtest_run.py` نمای سادهٔ کل زیرسیستم موتور، آمار، خلاصه‌نویس و نویسندگان JSON است. هم CLI و هم API از همین یک در وارد می‌شوند.

### ۴.۶. کنترل‌کنندهٔ جلویی — Front Controller / Router

کلاس `ViewerApi` نقش مسیریاب را دارد و `app.py` صرفاً مکانیک پروتکل را انجام می‌دهد. مهم‌ترین دستاورد این جداسازی، **آزمون‌پذیری** است: هندلرها دیکشنری می‌گیرند و `Response` برمی‌گردانند، بنابراین می‌توان بدون باز کردن سوکت آن‌ها را فراخواند.

### ۴.۷. انتشار-اشتراک — Publish/Subscribe (در فرانت‌اند)

> **تعریف:** فرستنده و گیرنده مستقیماً از یکدیگر بی‌خبرند و از طریق یک کانال میانی ارتباط برقرار می‌کنند.

جدول معاملات باید نمودار را به معامله‌ای ببرد و نمودار باید سطر مربوطه را برجسته کند. اتصال مستقیم آن‌ها یک **وابستگی دوری (Circular Dependency)** می‌ساخت. راه‌حل، یک گذرگاه رویداد ۲۱ خطی است:

```javascript
/* گذرگاه رویداد سه‌خطی.
   جدول معاملات نیاز دارد نمودار به معامله زوم کند؛ نمودار نیاز دارد جدول
   سطر را برجسته کند. اتصال مستقیم، بارگذاری هرکدام بدون دیگری را
   ناممکن می‌کرد، پس هر دو از اینجا صحبت می‌کنند. */
export function on(event, handler) { ... }
export function emit(event, payload) { ... }

export const EVENTS = {
  TRADE_SELECTED: 'trade:selected',
  DATA_RELOADED: 'data:reloaded',
};
```

### ۴.۸. الگوی کارخانه — Factory Method

سه نمونه: `triggers_from_params()`، `Params.from_dict()` و `WalkForwardConfig.from_request()`. هرکدام مسئولیت ساخت یک شیء معتبر از ورودی خام را متمرکز می‌کنند.

### ۴.۹. مدیر زمینه — Context Manager

قفل اجرای بک‌تست در سرور، به‌شکل یک مدیر زمینه پیاده شده تا فراخوان‌کننده هرگز فراموش نکند قفل را آزاد کند:

```python
with self.state.try_run() as acquired:
    if not acquired:
        return error(409, "a backtest is already running, try again in a moment")
    ...
```

---

## ۵. راهبرد تست و تضمین صحت (Testing & Correctness Strategy)

### ۵.۱. تست‌های واحد

فایل `tests/test_units.py` شامل **۴۷ تست** است که در حدود ۵ میلی‌ثانیه اجرا می‌شوند:

```bash
python3 -m unittest discover tests
```

نکتهٔ مهم و عمدی: **هیچ‌کدام از این تست‌ها به فایل `5m_candles.json` (۶۷ مگابایت) نیاز ندارند.** این دقیقاً چیزی است که بازآرایی به دست آورد — قوانین (پر شدن سفارش، حفره‌ها، محاسبهٔ حجم، امتیازدهی، بازنمونه‌برداری) از سری میلیون‌کندلی که معمولاً روی آن اعمال می‌شوند، قابل تفکیک شدند.

پوشش تست‌ها:

| کلاس تست | موضوع |
| --- | --- |
| `ParamsTest` | تبدیل نوع، کلیدهای ناشناخته، حالت سخت‌گیرانه، عدم تغییر پایه |
| `TimeframeTest` | تفکیک حفره از تعطیلی، عدم عبور سطل از حفره، حفظ حجم |
| `SeriesTest` | پنجرهٔ زمانی، تشخیص ترتیب نادرست |
| `SpreadTest` | هزینهٔ یک رفت‌وبرگشت، اسپرد منفی |
| `BrokerTest` | تقدم حد ضرر، گپ در بازگشایی، تقارن خرید و فروش |
| `PositionTest` | جهت‌مندی MAE/MFE، سود شناور |
| `AccountTest` | ثبت معامله، محاسبهٔ حجم |
| `DailyLossLimitTest` | فعال شدن، بازنشانی روزانه، حالت غیرفعال |
| `GapPolicyTest` | مسطح‌سازی، مسدودسازی ورود، غیرفعال‌سازی |
| `StatisticsTest` | شاخص‌های اصلی، اجرای خالی، افت سرمایه از قله |
| `ObjectiveTest` | رد ورشکستگی، درجه‌بندی، سقف افت سرمایه |
| `SearchSpaceTest` | نگاشت نام‌ها، ایزوله‌سازی محرک‌ها |
| `WalkForwardTest` | تعداد چین‌ها، ورودی نامعتبر |
| `UtilTest` | تحلیل تاریخ، نازک‌سازی |

### ۵.۲. تأیید هم‌ارزی (Equivalence Verification)

بازآرایی‌ای در این مقیاس تنها زمانی قابل اعتماد است که ثابت شود رفتار **دقیقاً** حفظ شده است. روش به‌کاررفته، مقایسهٔ بایت‌به‌بایت خروجی پیاده‌سازی قدیم و جدید بود:

- **بک‌تست:** فایل `results.json`، برش نمودار، و تک‌تک رکوردهای معاملات روی یک اجرای نیمهٔ اول ۲۰۲۴ **کاملاً یکسان** بودند.
- **پنج پیکربندی دیگر موتور:** حفره‌های داده، دورهٔ گرم‌شدن پس از حفره، ورشکستگی، فیلتر جلسهٔ نیویورک، و هرم‌سازی محدود — همگی معاملهٔ‌به‌معامله مطابقت داشتند.
- **بهینه‌ساز:** یک اجرای کامل walk-forward (پیکربندی، چین‌ها، نتایج خارج از نمونه، و توصیهٔ نهایی) دقیقاً یکسان بود.
- **تبدیل CSV:** فایل JSON تولیدشده بایت‌به‌بایت یکسان بود.
- **رابط کاربری:** تمام مسیرها در مرورگر واقعی آزموده شدند — تعویض تایم‌فریم، انتخاب معامله، تمام دکمه‌های نوار ابزار، مودال ماهانه، کشوها، و یک چرخهٔ کامل اجرای مجدد. بدون خطا در کنسول.

---

## ۶. بازبینی انتقادی و نقاط قابل بهبود (Critical Review)

هیچ معماری‌ای بی‌نقص نیست. موارد زیر، بدهی‌های باقی‌مانده و پیشنهادهای بهبود هستند.

### ۶.۱. نشت لایه‌ای در `BacktestResult`

فیلد `signals` در `BacktestResult` کل شیء `SignalSet` را حمل می‌کند، در حالی که تنها مصرف‌کنندهٔ آن، نویسندهٔ نمودار است که فقط به دو آرایهٔ EMA نیاز دارد. این یعنی یک شیء از لایهٔ پایین‌تر (`signals`) به فراخوان‌کنندگان لایه‌های بالاتر نشت می‌کند.

**پیشنهاد:** تنها همان دو آرایه منتقل شوند، یا یک شیء کوچک `ChartOverlays` معرفی شود.

### ۶.۲. واردسازی درون‌تابعی باقی‌مانده

در انتهای `midas/engine/backtester.py`:

```python
def _date(timestamp) -> str:
    from ..util.timeutil import format_minute
    return format_minute(timestamp)
```

این واردسازی درون تابع، بازمانده‌ای از دورهٔ گذار است و دلیلی برای وجودش نیست.

**پیشنهاد:** به واردسازی سطح ماژول منتقل و تابع پوششی حذف شود.

### ۶.۳. دیکشنری آمار — آخرین بازماندهٔ وسواس نوع اولیه

تابع `compute_statistics` یک `dict` با حدود ۳۰ کلید رشته‌ای برمی‌گرداند. مصرف‌کنندگان (خلاصهٔ ترمینال، نویسندهٔ JSON، تابع هدف بهینه‌ساز، و رابط کاربری) همگی با کلید رشته‌ای به آن دسترسی دارند و یک غلط املایی در کلید، فقط در زمان اجرا کشف می‌شود.

**دلیل وضعیت فعلی:** این دیکشنری مستقیماً به `results.json` سریال می‌شود و مرورگر آن را می‌خواند؛ تبدیل آن به دیتاکلاس نیازمند یک لایهٔ سریال‌سازی است.

**پیشنهاد:** یک دیتاکلاس `Statistics` با متد `as_dict()` — دقیقاً همان الگویی که برای `Trade` استفاده شده است.

### ۶.۴. محاسبهٔ غیرضروری در محرک‌های غیرفعال

متد `Trigger.detect` ابتدا `_detect` را اجرا می‌کند و سپس اگر محرک غیرفعال باشد، ماسک صفر برمی‌گرداند. یعنی محاسبات برداری برای محرکی که خاموش است هم انجام می‌شود.

این از نظر صحت مشکلی ندارد (و در بهینه‌ساز که محرک‌ها ایزوله می‌شوند، هزینهٔ محسوسی دارد).

**پیشنهاد:** بررسی `enabled` پیش از فراخوانی `_detect` انجام شود. نکتهٔ ظریف: ماسک‌های محرک ۱ به‌عنوان ورودی مشترک محرک‌های ۲ و ۳ استفاده می‌شوند و باید صرف‌نظر از فعال بودن محرک ۱ محاسبه شوند — این محاسبه در `generator._trigger_context` انجام می‌شود و مستقل است، بنابراین بهینه‌سازی بالا امن است.

### ۶.۵. نبود تست یکپارچگی سرتاسری

تست‌های فعلی همگی واحد هستند. صحت سرتاسری با مقایسه در برابر کد قدیمی تأیید شد، اما آن کد اکنون حذف شده است؛ یعنی این شبکهٔ ایمنی دیگر در دسترس نیست.

**پیشنهاد (بالاترین اولویت):** یک **تست فایل طلایی (Golden File Test)** روی یک سری مصنوعی کوچک (مثلاً ۲٬۰۰۰ کندل ساختگی با یک حفرهٔ عمدی) که خروجی `results.json` را با یک فایل مرجع مقایسه کند. این کار، پوشش سرتاسری را بدون نیاز به فایل ۶۷ مگابایتی فراهم می‌کند.

### ۶.۶. فرضیات مربوط به وضعیت سرور

`ViewerState.series` یک وضعیت اشتراکی در سطح فرایند است و `BackgroundJob` تنها یک شکاف کاری دارد. این طراحی برای یک ابزار محلی تک‌کاربره کاملاً مناسب است، اما مقیاس‌پذیر نیست.

**پیشنهاد:** در صورت نیاز به چند کاربر، به یک صف کار (Job Queue) با شناسهٔ کار مهاجرت شود. در وضعیت فعلی، این یک **محدودیت آگاهانه** است نه یک نقص.

### ۶.۷. فرانت‌اند بدون تست و بدون مرحلهٔ ساخت

ماژول‌های ES نیازمند سرو شدن از طریق HTTP هستند (پروتکل `file://` کار نمی‌کند) و هیچ تستی برای منطق خالص فرانت‌اند وجود ندارد.

**پیشنهاد:** توابع خالص `timeframes.js`، `smoothing.js`، `sizeCompare.js` و `monthly.js` بهترین نامزدها برای تست هستند و می‌توان با یک اجراکنندهٔ سبک آن‌ها را پوشش داد. مهم‌تر آنکه منطق بازنمونه‌برداری در دو زبان پیاده‌سازی شده (پایتون و جاوااسکریپت) و یک تست هم‌ارزی میان آن دو ارزشمند است.

### ۶.۸. دیتاکلاس بزرگ `Params`

کلاس `Params` با ۴۵ فیلد مسطح، در آستانهٔ تبدیل شدن به یک **شیء خدا (God Object)** است.

**دلیل وضعیت فعلی:** ساختار مسطح مستقیماً با قالب سیمی فرم رابط کاربری و فضای جست‌وجوی Optuna مطابقت دارد و تودرتو کردن آن، هر دو را پیچیده می‌کند.

**پیشنهاد:** در صورت رشد بیشتر، گروه‌بندی به `TriggerParams`، `RiskParams` و `SessionParams` با حفظ `from_dict` مسطح به‌عنوان لایهٔ سازگاری.

### ۶.۹. پکیج تک‌ماژولی `midas/config/`

این پکیج تنها شامل `params.py` است. این یک ایراد جزئی است و صرفاً برای تقارن ساختاری نگه داشته شده.

---

## ۷. پیوست: راهنمای اجرا (Appendix)

### ۷.۱. آماده‌سازی داده

```bash
# فایل CSV خام را در data.csv یا ~/XAU_5m_data.csv قرار دهید، سپس:
python3 convert_csv.py
```

### ۷.۲. اجرای بک‌تست

```bash
python3 backtest.py --quiet
```

```bash
python3 backtest.py --start 2024-01-01 --end 2024-12-31 --capital 10000
```

### ۷.۳. بررسی یکپارچگی داده

```bash
python3 timeframes.py --data 5m_candles.json --tf 1h
```

### ۷.۴. بهینه‌سازی

```bash
python3 optimize.py --groups t1 t2 t3 exposure --trials 80
```

### ۷.۵. اجرای نمایشگر

```bash
midas
```

```bash
python3 serve.py
```

### ۷.۶. اجرای تست‌ها

```bash
python3 -m unittest discover tests
```

---

## جمع‌بندی

معماری فعلی MidasScript بر سه ستون استوار است:

1. **جهت وابستگی یک‌طرفه** — هر لایه فقط به لایه‌های پایین‌تر از خود وابسته است و دو ثابت معماری (`print` فقط در لایهٔ گزارش، HTTP فقط در لایهٔ سرور) این جهت را حفظ می‌کنند.
2. **جدایی قانون از هماهنگی** — حلقهٔ اصلی بک‌تست فقط ترتیب رویدادها را می‌داند؛ قوانین پر شدن سفارش، حفره‌ها، محاسبهٔ حجم و محدودیت زیان، هرکدام در ماژول مستقل و آزمون‌پذیر خود زندگی می‌کنند.
3. **اشیای مقداری به‌جای انواع اولیه** — تاپل‌ها و دیکشنری‌های بی‌نام جای خود را به انواع دامنه‌ای داده‌اند که خودشان می‌دانند چه کاری می‌توانند انجام دهند.

نتیجهٔ عملی این سه ستون در یک جمله: **افزودن یک محرک ورود جدید، یک نقطهٔ پایانی جدید، یا یک معیار بهینه‌سازی جدید، هیچ‌کدام نیازمند دست زدن به کد آزموده‌شدهٔ موجود نیست.**
