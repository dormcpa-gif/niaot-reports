import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type DeepAnalysisResult } from "../api/client";

function riskClass(risk: string | undefined): string {
  if (risk === "high") return "error";
  if (risk === "medium") return "needs-review";
  return "hint";
}

export default function DeepAnalysisResultPage() {
  const { analysisId } = useParams<{ analysisId: string }>();
  const [result, setResult] = useState<DeepAnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!analysisId) return;
    api.getDeepAnalysis(analysisId).then(setResult).catch((e) => setError(String(e)));
  }, [analysisId]);

  if (error) return <p className="error">{error}</p>;
  if (!result) return <p>טוען...</p>;

  const s = result.structured;

  return (
    <div className="page">
      <h1>ניתוח מעמיק — תוצאה</h1>
      <p>
        <Link to="/analysis">← ניתוח חדש</Link>
        {" · "}
        <Link to={`/clients/${result.client_id}`}>דוחות הלקוח</Link>
      </p>

      <p className="hint" style={{ fontWeight: "bold" }}>
        ⚠ זוהי טיוטת נייר עבודה שהופקה אוטומטית על ידי מודל שפה ({result.model}) - חובה על רו"ח לבדוק, לתקן ולאשר כל
        נתון ומספר לפני הגשה. המערכת אינה מגישה דבר ואינה קובעת עמדה סופית.
      </p>

      <section className="card">
        <h2>מסמכי מקור שנותחו</h2>
        <ul>
          {result.input_documents.map((d, i) => (
            <li key={i}>
              {d.filename}
              {d.extraction_note && <span className="error"> — {d.extraction_note}</span>}
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h2>סיכום מילולי</h2>
        <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit" }}>{result.narrative}</pre>
      </section>

      {result.structured_parse_error && <p className="error">{result.structured_parse_error}</p>}

      {s && (
        <>
          {s.residency && (
            <section className="card">
              <h2>הכרעות מקדימות</h2>
              <p>
                תושבות ישראלית: <b>{s.residency.israeli_resident ? "כן" : "לא"}</b> (ביטחון:{" "}
                {s.residency.confidence}) — {s.residency.basis}
              </p>
              {s.credit_direction && (
                <p>
                  כיוון זיכוי מס זר: <b>{s.credit_direction.value}</b> — {s.credit_direction.reasoning}
                </p>
              )}
            </section>
          )}

          {Array.isArray(s.open_issues) && s.open_issues.length > 0 && (
            <section className="card">
              <h2>הכרעות פתוחות / חשיפות</h2>
              <table>
                <thead>
                  <tr>
                    <th>סוגיה</th>
                    <th>סוג</th>
                    <th>סכום ($)</th>
                    <th>סיכון</th>
                    <th>פירוט</th>
                  </tr>
                </thead>
                <tbody>
                  {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                  {s.open_issues.map((issue: any, i: number) => (
                    <tr key={i} className={riskClass(issue.risk)}>
                      <td>{issue.issue}</td>
                      <td>{issue.type}</td>
                      <td>{issue.amount_usd}</td>
                      <td>{issue.risk}</td>
                      <td>{issue.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {Array.isArray(s.missing_documents) && s.missing_documents.length > 0 && (
            <section className="card">
              <h2>מסמכים חסרים</h2>
              <ul>
                {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                {s.missing_documents.map((m: any, i: number) => (
                  <li key={i}>{typeof m === "string" ? m : JSON.stringify(m)}</li>
                ))}
              </ul>
            </section>
          )}

          {Array.isArray(s.cross_checks) && s.cross_checks.length > 0 && (
            <section className="card">
              <h2>בקרות הצלבה</h2>
              <table>
                <thead>
                  <tr>
                    <th>בקרה</th>
                    <th>חושב</th>
                    <th>צפוי</th>
                    <th>סטטוס</th>
                  </tr>
                </thead>
                <tbody>
                  {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                  {s.cross_checks.map((c: any, i: number) => (
                    <tr key={i} className={c.status === "deviation" ? "error" : ""}>
                      <td>{c.check}</td>
                      <td>{c.computed}</td>
                      <td>{c.expected}</td>
                      <td>{c.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {Array.isArray(s.form_1301_mapping) && s.form_1301_mapping.length > 0 && (
            <section className="card">
              <h2>מיפוי לטופס 1301</h2>
              <table>
                <thead>
                  <tr>
                    <th>חלק</th>
                    <th>תיאור</th>
                    <th>סכום (₪)</th>
                    <th>קוד שדה</th>
                  </tr>
                </thead>
                <tbody>
                  {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                  {s.form_1301_mapping.map((f: any, i: number) => (
                    <tr key={i}>
                      <td>{f.part}</td>
                      <td>{f.description}</td>
                      <td>{f.amount_ils ?? "—"}</td>
                      <td>{f.field_code ?? "לאימות מול הטופס"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          <details className="card">
            <summary>JSON מלא (למפתחים/לבדיקה)</summary>
            <pre style={{ whiteSpace: "pre-wrap", overflowX: "auto" }}>{JSON.stringify(s, null, 2)}</pre>
          </details>
        </>
      )}
    </div>
  );
}
