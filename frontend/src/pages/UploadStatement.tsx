import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Client } from "../api/client";

export default function UploadStatement() {
  const navigate = useNavigate();
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState("");
  const [newClientName, setNewClientName] = useState("");
  const [newClientTaxFile, setNewClientTaxFile] = useState("");
  const [taxYear, setTaxYear] = useState(new Date().getFullYear() - 1);
  const [broker, setBroker] = useState("IBKR");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listClients().then(setClients).catch((e) => setError(String(e)));
  }, []);

  async function handleCreateClient() {
    if (!newClientName.trim()) return;
    setError(null);
    try {
      const c = await api.createClient(newClientName.trim(), newClientTaxFile.trim() || null);
      setClients((prev) => [...prev, c]);
      setSelectedClientId(c.id);
      setNewClientName("");
      setNewClientTaxFile("");
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleUpload() {
    if (!selectedClientId || !file) {
      setError("יש לבחור לקוח ולהעלות קובץ PDF");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const summary = await api.uploadStatement(selectedClientId, taxYear, broker, file);
      navigate(`/review/${summary.id}`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h1>העלאת דוח ברוקר</h1>

      <section className="card">
        <h2>לקוח</h2>
        <div className="row">
          <select value={selectedClientId} onChange={(e) => setSelectedClientId(e.target.value)}>
            <option value="">בחר לקוח קיים...</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.full_name} {c.tax_file_number ? `(תיק ${c.tax_file_number})` : ""}
              </option>
            ))}
          </select>
          {selectedClientId && <Link to={`/clients/${selectedClientId}`}>צפייה בדוחות קודמים של לקוח זה</Link>}
        </div>
        <details>
          <summary>או צור לקוח חדש</summary>
          <div className="row">
            <input
              placeholder="שם מלא"
              value={newClientName}
              onChange={(e) => setNewClientName(e.target.value)}
            />
            <input
              placeholder="מספר תיק ברשות המסים (לא חובה)"
              value={newClientTaxFile}
              onChange={(e) => setNewClientTaxFile(e.target.value)}
            />
            <button onClick={handleCreateClient}>צור לקוח</button>
          </div>
        </details>
      </section>

      <section className="card">
        <h2>פרטי הדוח</h2>
        <div className="row">
          <label>
            שנת מס
            <input
              type="number"
              value={taxYear}
              onChange={(e) => setTaxYear(Number(e.target.value))}
            />
          </label>
          <label>
            ברוקר / מסמך
            <select value={broker} onChange={(e) => setBroker(e.target.value)}>
              <option value="IBKR">Interactive Brokers (IBKR / IBKR UK / CE) - PDF</option>
              <option value="ETORO">eToro - קובץ Excel (Account Statement)</option>
              <option value="SCHWAB">Charles Schwab - PDF (דוח חשבון)</option>
              <option value="TD_AMERITRADE">TD Ameritrade - PDF (דוח חשבון, פורמט Schwab)</option>
              <option value="TRADESTATION">TradeStation - קובץ CSV (Tax Center / פעילות מזומן)</option>
              <option value="K1">Schedule K-1 (Form 1065) - PDF</option>
              <option value="FORM_1040">Form 1040 - PDF (רק כשאין דוח ברוקר מפורט)</option>
            </select>
          </label>
        </div>
        {broker === "ETORO" && (
          <p className="hint">
            ⚠ פרסר eToro טרם נבדק מול דוח אמיתי (מבוסס על תיעוד מבנה עמודות ממקור חיצוני אמין). יש לבדוק את התוצאות
            בקפידה יתרה במסך הסיווג לפני שימוש.
          </p>
        )}
        {(broker === "SCHWAB" || broker === "TD_AMERITRADE") && (
          <p className="hint">
            ⚠ פרסר Schwab/TD Ameritrade זה טרם נבדק מול דוח אמיתי (מבוסס על מדריך ציבורי בלבד). מזהה רק
            דיבידנד/ריבית - רווח הון ממכירת ני"ע דורש הזנה ידנית (אין נתון עלות בסיס בדוח זה).
          </p>
        )}
        {broker === "TRADESTATION" && (
          <p className="hint">
            ⚠ פרסר TradeStation זה טרם נבדק מול קובץ אמיתי (מבוסס על תיעוד עמודות כללי). יש לוודא שהקובץ הוא
            ייצוא CSV של "Realized Gain/Loss" או של פעילות מזומן (Cash Activity).
          </p>
        )}
        {broker === "K1" && (
          <p className="hint">
            ⚠ פרסר K-1 זה טרם נבדק מול מסמך אמיתי. מזהה רק תיבות 5/6a/8/9a - פרטי מס זר (תיבה 16 /
            Schedule K-3) אינם ממופים אוטומטית ויש להזין ידנית.
          </p>
        )}
        {broker === "FORM_1040" && (
          <p className="hint">
            ⚠ טופס 1040 הוא מסמך סיכום מצטבר. אין להעלות אותו יחד עם דוח ברוקר מפורט לאותו חשבון/שנה - הדבר
            יגרום לכפל ספירה של אותה הכנסה. יש להשתמש בו רק כשאין דוח ברוקר מפורט זמין.
          </p>
        )}
        <div className="row">
          <input
            type="file"
            accept={broker === "ETORO" ? ".xlsx" : broker === "TRADESTATION" ? ".csv" : "application/pdf"}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>
        <button disabled={busy} onClick={handleUpload}>
          {busy ? "מעלה ומעבד..." : "העלה ונתח דוח"}
        </button>
      </section>

      {error && <p className="error">{error}</p>}
    </div>
  );
}
