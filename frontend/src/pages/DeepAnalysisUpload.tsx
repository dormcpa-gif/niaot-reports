import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Client, type DeepAnalysisSummary } from "../api/client";

export default function DeepAnalysisUpload() {
  const navigate = useNavigate();
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState("");
  const [taxYear, setTaxYear] = useState(new Date().getFullYear() - 1);
  const [clientContext, setClientContext] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [history, setHistory] = useState<DeepAnalysisSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listClients().then(setClients).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!selectedClientId) {
      setHistory([]);
      return;
    }
    api.listDeepAnalysesForClient(selectedClientId).then(setHistory).catch(() => setHistory([]));
  }, [selectedClientId]);

  async function handleSubmit() {
    if (!selectedClientId || files.length === 0) {
      setError("יש לבחור לקוח ולהעלות לפחות מסמך אחד (1040, נספחים, K-1, דוח מדינה, דוח ברוקר וכו')");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.createDeepAnalysis(selectedClientId, taxYear, files, clientContext);
      navigate(`/analysis/${result.id}`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h1>ניתוח מעמיק (בינה מלאכותית) — דוחות מס זרים</h1>
      <p className="hint">
        ⚠ תכונה זו מפעילה מודל שפה (Claude) על תוכן המסמכים שהועלו, בהתאם ל"פרומפט מערכת" שהוגדר על ידך
        (הכרעות תושבות, כיוון זיכוי מס זר, מלכודות מוכרות ומיפוי לטופס 1301). <b>הפלט הוא טיוטת נייר עבודה בלבד</b> -
        חובה על רו"ח לבדוק, לתקן ולאשר כל נתון ומספר לפני שימוש. המערכת אינה מגישה דבר ואינה קובעת עמדה סופית.
      </p>

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
      </section>

      <section className="card">
        <h2>מסמכי מקור</h2>
        <p className="hint">
          העלו את כל המסמכים הרלוונטיים יחד: 1040/1040-SR/1040-NR, נספחי Schedule (B/D/E/8582/8995/1116/8833),
          דוחות מדינה, 1099 מאוחד, Activity Statement, K-1 וכו'. ניתן לבחור מספר קבצים בבת אחת (PDF מועדף; קבצי
          טקסט/CSV גם נתמכים).
        </p>
        <div className="row">
          <label>
            שנת מס
            <input type="number" value={taxYear} onChange={(e) => setTaxYear(Number(e.target.value))} />
          </label>
        </div>
        <div className="row">
          <input
            type="file"
            multiple
            accept="application/pdf,.csv,.txt"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
          />
        </div>
        {files.length > 0 && (
          <ul>
            {files.map((f, i) => (
              <li key={i}>{f.name}</li>
            ))}
          </ul>
        )}
        <div className="row">
          <label style={{ width: "100%" }}>
            הקשר נוסף ללקוח (לא חובה) - למשל: אזרחות אמריקאית, עולה חדש/תושב חוזר, פרטים שכדאי שהמודל ידע
            <textarea
              rows={3}
              style={{ width: "100%" }}
              value={clientContext}
              onChange={(e) => setClientContext(e.target.value)}
            />
          </label>
        </div>
        <button disabled={busy} onClick={handleSubmit}>
          {busy ? "מריץ ניתוח (עשוי לקחת עד דקה)..." : "הרץ ניתוח מעמיק"}
        </button>
      </section>

      {error && <p className="error">{error}</p>}

      {history.length > 0 && (
        <section className="card">
          <h2>ניתוחים קודמים ללקוח זה</h2>
          <table>
            <thead>
              <tr>
                <th>תאריך</th>
                <th>שנת מס</th>
                <th>קבצים</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.id}>
                  <td>{new Date(h.created_at).toLocaleString("he-IL")}</td>
                  <td>{h.tax_year}</td>
                  <td>{h.input_filenames.join(", ")}</td>
                  <td>
                    <Link to={`/analysis/${h.id}`}>צפייה</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
