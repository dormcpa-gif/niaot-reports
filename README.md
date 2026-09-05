# מערכת דוחות ני"ע

MVP: קליטת דוח Activity Statement של Interactive Brokers (IBKR), חילוץ דיבידנדים/ריבית/רווח הון/עמלות, וסיוע בהפקת **נספח עזר** בפורמט תואם לנספח ג' (רווח הון מני"ע) ונספח ד' (הכנסות חו"ל) של טופס 1301 — כולל **דוח הסבר/מעקב** שמקשר כל סכום לשורת המקור בדוח הברוקר.

ראו את מסמך התכנון המלא: `C:\Users\User\.claude\plans\fuzzy-bubbling-catmull.md`

## מה המערכת עושה (ומה לא)

- מחלצת נתונים מדוח IBKR PDF ומסווגת אותם אוטומטית לפי חוקים ברורים בלבד (למשל: דיבידנד רגיל → שדה 462).
- **כל דבר שדורש שיקול דעת מקצועי (מדרגת מס, "בעל מניות מהותי", ניכוי עמלות) מסומן `needs_review` ודורש אישור/עריכה של רו"ח** לפני הפקת הפלט הסופי.
- אינה מגישה שום דבר לרשות המסים — הפלט הוא קובץ Excel עזר בלבד.
- הוספת ברוקרים/מסמכים נוספים דורשת רק פרסר חדש תחת `backend/app/parsers/` (ראו "הרחבה לברוקר/מסמך נוסף" למטה).
- דוחות שאינם בפורמט הצפוי, או חשבונות שמטבע הבסיס שלהם אינו USD, נדחים עם הודעת שגיאה ברורה בזמן ההעלאה — במקום לעבד אותם בשקט ולהפיק מספרים שגויים.

### מצב תמיכה בברוקרים

| ברוקר | סטטוס | הערות |
|---|---|---|
| **IBKR** | ✅ נבדק מול דוח אמיתי | הפרסר ומיפוי השדות אומתו מול Activity Statement אמיתי ומספרים תואמים במדויק. |
| **eToro** | ⚠ לא נבדק מול דוח אמיתי | הפרסר (`parsers/etoro_statement.py`) קורא את קובץ ה-XLSX (Account Statement), מבוסס על מבנה עמודות מתועד מפרויקטי קוד פתוח פעילים ([masbug/etoro-edavki](https://github.com/masbug/etoro-edavki), [weirdapps/etoro_statement](https://github.com/weirdapps/etoro_statement)) שרצים בפועל מול דוחות eToro אמיתיים - אמין יותר מניחוש, אך **טרם הורץ מול קובץ eToro אמיתי בקוד הזה**. יש לבדוק תוצאות בקפידה יתרה (המערכת מציגה אזהרה מתאימה במסך ההעלאה). |
| **IBKR UK/CE** | לא מומש כפרסר נפרד | הדוגמה הרשמית הציבורית שנמצאה מיושנת (2010) ולא תואמת את התבנית הנוכחית. עם זאת, הדוח האמיתי שנבדק עבור IBKR (US) מזכיר את "Interactive Brokers (U.K.) Limited" כגורם סליקה על אותה פלטפורמה/תבנית - סביר שהפרסר הקיים כבר תואם, **פרט למטבע**: אם חשבון ה-UK/אירופה נקוב בליש"ט/יורו ולא בדולר, ה-guardrail הקיים ידחה אותו במפורש במקום לחשב לפי שער שגוי. תמיכה בחשבון לא-דולרי תדרוש הרחבה ממוקדת של `currency_service`. |
| **Charles Schwab** | לא מומש | נמצא מדריך רשמי (schwab.com/resource/statement-guide) עם תרשים מבנה טבלת Transactions (Date, Category, Action, Symbol/CUSIP, Description, Quantity, Price/Rate, Charges/Interest, Amount), אך זו תמונה סרוקה בתוך ה-PDF ולא טקסט הניתן לחילוץ - לא ניתן לבנות ולבדוק פרסר regex בלעדיו. דורש PDF אמיתי (לא סרוק). |
| **TradeStation** | לא מומש | לא נמצא PDF/CSV לדוגמה ציבורי. TradeStation HUB כן מציע ייצוא CSV (Tax Center) - עדיף על PDF לפרסור אמין; מומלץ לבקש דוגמת CSV אמיתית במקום PDF. |

## הרצה מקומית

### Backend (FastAPI)

```bash
cd backend
pip install -e .
uvicorn app.main:app --reload --port 8000
```

בדיקות:

```bash
cd backend
pip install -e ".[dev]"
pytest
```

### Frontend (React + Vite)

```bash
cd frontend
npm install
npm run dev
```

האפליקציה עולה על http://localhost:5173 ומדברת עם ה-API ב-http://localhost:8000.

## זרימת עבודה

1. **העלאה** (`/`) — בחירת/יצירת לקוח, שנת מס, והעלאת PDF של דוח IBKR.
2. **בדיקת סיווג** (`/review/:id`) — טבלה של כל הדיבידנדים/ריבית/רווח הון/עמלות, עם שדה היעד המוצע בנספח ד'/ג' וסימון `needs_review`. ניתן לשנות ולשמור.
3. **הפקת נספח** (`/preview/:id`) — הזנת שער/י המרה דולר→שקל (שער יחיד ליום מוקדם משמש כברירת מחדל לכל השנה, או שערים נקודתיים לפי תאריך), והורדת קובץ Excel עם שלוש לשוניות: נספח ד', נספח ג', והסבר ומעקב.
4. **לקוחות** (`/clients`, `/clients/:id`) — רשימת כל הלקוחות, ולכל לקוח היסטוריית הדוחות שהועלו עבורו (עם קישור ישיר לבדיקת הסיווג ולהפקת הנספח של כל דוח).

## מבנה הקוד

```
backend/app/
  parsers/        # IBKR (וברוקרים עתידיים) -> NormalizedStatement
  models/         # מודלים מנורמלים (Dividend, Trade, InterestItem, FeeItem)
  mapping/        # NormalizedStatement -> שדות נספח ג'/ד' (עם כללי סיווג מפורשים)
  services/       # תזמור (extraction), המרת מטבע, בניית הדוח
  output/         # ייצוא ל-Excel
  api/            # נתיבי FastAPI
  db/             # SQLAlchemy (SQLite מקומי)
frontend/src/
  pages/          # UploadStatement, ReviewTransactions, AppendixPreview, ClientsIndex, ClientStatements
  api/client.ts   # קליינט REST
```

## הרחבה לברוקר/מסמך נוסף

1. ממשו מחלקה חדשה תחת `backend/app/parsers/` שמחזירה `NormalizedStatement` (אותם מודלים בדיוק: `Dividend`, `InterestItem`, `Trade`, `FeeItem`).
2. רשמו אותה ב-`_PARSERS` בתוך `backend/app/services/extraction_service.py`.
3. שכבות המיפוי (`mapping/`), השירותים (`services/`) והפלט (`output/`) לא צריכות להשתנות כלל.
