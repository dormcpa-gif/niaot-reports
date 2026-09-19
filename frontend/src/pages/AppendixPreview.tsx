import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type StatementDetail } from "../api/client";

const radioLabelStyle = { flexDirection: "row", alignItems: "center", gap: 8, fontSize: 15, color: "inherit" } as const;

interface RateRow {
  on_date: string;
  rate: string;
}

export default function AppendixPreview() {
  const { statementId } = useParams<{ statementId: string }>();
  const [detail, setDetail] = useState<StatementDetail | null>(null);
  const [rates, setRates] = useState<RateRow[]>([]);
  const [useBoi, setUseBoi] = useState(true);
  const [acqDates, setAcqDates] = useState<Record<string, string>>({});
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
    const parsedRates = useBoi
      ? []
      : rates.filter((r) => r.on_date && r.rate).map((r) => ({ currency: "USD", on_date: r.on_date, rate: Number(r.rate) }));
    if (!useBoi && parsedRates.length === 0) {
      setError("בהזנה ידנית יש להזין לפחות שער המרה אחד, או לבחור בשערי בנק ישראל");
      return;
    }
    const acquisitionDates = Object.fromEntries(Object.entries(acqDates).filter(([, d]) => d));
    setBusy(true);
    setError(null);
    try {
      const blob = await api.downloadAppendix(statementId, parsedRates, { useBoiRates: useBoi, acquisitionDates });
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

  const symbolsMissingPurchaseDate = Array.from(
    new Set(
      detail.classified
        .filter((c) => c.source_kind === "trade" && c.lot_level && !c.open_date && c.symbol)
        .map((c) => c.symbol as string)
    )
  ).sort();

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

      {(detail.statement.warnings?.length ?? 0) > 0 && (
        <section className="card">
          <h2>אזהרות בדוח</h2>
          <ul>
            {detail.statement.warnings!.map((w, i) => (
              <li key={i} className="error">
                {w}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <h2>שערי המרה (דולר → שקל)</h2>
        <label style={radioLabelStyle}>
          <input type="radio" style={{ width: "auto", padding: 0 }} checked={useBoi} onChange={() => setUseBoi(true)} /> שער יציג של בנק ישראל לכל יום עסקים
          (מומלץ)
        </label>
        <p className="hint">
          השערים נשלפים אוטומטית מבנק ישראל לכל תאריך עסקה, רכישה ומכירה - כנדרש לחישוב רווח הון לפי לוט. בסוף שבוע
          וחג משמש השער האחרון שקדם להם, ומסומן בגיליון ההסבר.
        </p>
        <label style={radioLabelStyle}>
          <input type="radio" style={{ width: "auto", padding: 0 }} checked={!useBoi} onChange={() => setUseBoi(false)} /> הזנה ידנית
        </label>
        {!useBoi && (
          <>
            <p className="hint">
              שער שמוזן ליום מוקדם משמש כברירת מחדל ("fallback") לכל עסקה מאוחרת יותר עד שער חדש. שים לב: שער יחיד לכל
              השנה אינו מאפשר חישוב לפי לוט.
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
          </>
        )}
      </section>

      {symbolsMissingPurchaseDate.length > 0 && (
        <section className="card">
          <h2>תאריכי רכישה חסרים</h2>
          <p className="hint">
            לניירות הבאים נמכרו יחידות שנרכשו לפני תחילת הדוח (או הועברו לחשבון), ולכן תאריך הרכישה אינו מופיע בו. ללא
            תאריך, הרווח מחושב בשער יום המכירה בלבד ועלול להיות מוגזם. אפשר להזין את תאריך הרכישה (מדוח שנה קודמת
            או מאישור הרכישה); שדה ריק משאיר את החישוב הזהיר וממשיך לסמן את הפריט.
          </p>
          {symbolsMissingPurchaseDate.map((sym) => (
            <div className="row" key={sym}>
              <span>{sym}</span>
              <input
                type="date"
                value={acqDates[sym] ?? ""}
                onChange={(e) => setAcqDates((prev) => ({ ...prev, [sym]: e.target.value }))}
              />
            </div>
          ))}
        </section>
      )}

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
