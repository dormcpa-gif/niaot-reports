import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type StatementDetail } from "../api/client";

interface RateRow {
  on_date: string;
  rate: string;
}

export default function AppendixPreview() {
  const { statementId } = useParams<{ statementId: string }>();
  const [detail, setDetail] = useState<StatementDetail | null>(null);
  const [rates, setRates] = useState<RateRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!statementId) return;
    api
      .getStatement(statementId)
      .then((d) => {
        setDetail(d);
        setRates([{ on_date: d.statement.period_start, rate: "" }]);
      })
      .catch((e) => setError(String(e)));
  }, [statementId]);

  function updateRate(index: number, patch: Partial<RateRow>) {
    setRates((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  function addRateRow() {
    setRates((prev) => [...prev, { on_date: "", rate: "" }]);
  }

  async function handleDownload() {
    if (!statementId) return;
    const parsedRates = rates
      .filter((r) => r.on_date && r.rate)
      .map((r) => ({ currency: "USD", on_date: r.on_date, rate: Number(r.rate) }));
    if (parsedRates.length === 0) {
      setError('יש להזין לפחות שער המרה אחד (למשל שער יציג ליום 1 בינואר, לשימוש כשער כלל-שנתי)');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const blob = await api.downloadAppendix(statementId, parsedRates);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `nespach_ezer_${statementId.slice(0, 8)}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !detail) return <p className="error">{error}</p>;
  if (!detail) return <p>טוען...</p>;

  return (
    <div className="page">
      <h1>הפקת נספח עזר</h1>
      <p>
        <Link to={`/review/${detail.id}`}>← חזרה לבדיקת סיווג</Link>
        {" · "}
        <Link to={`/clients/${detail.client_id}`}>דוחות הלקוח</Link>
      </p>
      <p>
        דוח {detail.broker} · שנת מס {detail.tax_year} · תקופה {detail.statement.period_start} עד{" "}
        {detail.statement.period_end}
      </p>

      <section className="card">
        <h2>שערי המרה (דולר → שקל)</h2>
        <p className="hint">
          שער שמוזן ליום מוקדם משמש כברירת מחדל ("fallback") לכל עסקה מאוחרת יותר עד שער חדש - כך ניתן להזין שער יציג
          יחיד לכל השנה (למשל 1 בינואר), או לפרט שערים חודשיים.
        </p>
        {rates.map((r, i) => (
          <div className="row" key={i}>
            <input type="date" value={r.on_date} onChange={(e) => updateRate(i, { on_date: e.target.value })} />
            <input
              type="number"
              step="0.0001"
              placeholder="שער (למשל 3.62)"
              value={r.rate}
              onChange={(e) => updateRate(i, { rate: e.target.value })}
            />
          </div>
        ))}
        <button onClick={addRateRow}>+ הוסף שער נוסף</button>
      </section>

      <button disabled={busy} onClick={handleDownload}>
        {busy ? "מפיק קובץ..." : "הורד נספח עזר (Excel)"}
      </button>

      {error && <p className="error">{error}</p>}

      <p className="hint">
        הקובץ כולל שלוש לשוניות: נספח ד' (הכנסות חו"ל לפי שדה), נספח ג' (רווח הון מני"ע לפי מדרגת מס), ולשונית "הסבר
        ומעקב" עם שורת המקור בדוח הברוקר לכל סכום - לשימוש כבסיס לביקורת לפני ההגשה.
      </p>
    </div>
  );
}
