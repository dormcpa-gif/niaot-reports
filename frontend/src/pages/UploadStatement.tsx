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
            ברוקר
            <select value={broker} onChange={(e) => setBroker(e.target.value)}>
              <option value="IBKR">Interactive Brokers (IBKR) - PDF</option>
              <option value="ETORO">eToro - קובץ Excel (Account Statement)</option>
            </select>
          </label>
        </div>
        {broker === "ETORO" && (
          <p className="hint">
            ⚠ פרסר eToro טרם נבדק מול דוח אמיתי (מבוסס על תיעוד מבנה עמודות ממקור חיצוני אמין). יש לבדוק את התוצאות
            בקפידה יתרה במסך הסיווג לפני שימוש.
          </p>
        )}
        <div className="row">
          <input
            type="file"
            accept={broker === "ETORO" ? ".xlsx" : "application/pdf"}
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
