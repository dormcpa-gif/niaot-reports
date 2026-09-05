import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type StatementDetail } from "../api/client";
import { NISPACH_C_BRACKETS, NISPACH_D_FIELD_LABELS, SOURCE_KIND_LABELS } from "../constants";

export default function ReviewTransactions() {
  const { statementId } = useParams<{ statementId: string }>();
  const [detail, setDetail] = useState<StatementDetail | null>(null);
  const [fieldOverrides, setFieldOverrides] = useState<Record<string, string | null>>({});
  const [bracketOverrides, setBracketOverrides] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!statementId) return;
    api
      .getStatement(statementId)
      .then((d) => {
        setDetail(d);
        setFieldOverrides(d.overrides.field_overrides ?? {});
        setBracketOverrides(d.overrides.bracket_overrides ?? {});
      })
      .catch((e) => setError(String(e)));
  }, [statementId]);

  async function handleSave() {
    if (!statementId) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateOverrides(statementId, fieldOverrides, bracketOverrides);
      setDetail(updated);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (!detail) return <p>טוען...</p>;

  const dividendAndInterestItems = detail.classified.filter((c) => c.source_kind === "dividend" || c.source_kind === "interest");
  const tradeItems = detail.classified.filter((c) => c.source_kind === "trade");
  const feeItems = detail.classified.filter((c) => c.source_kind === "fee");

  return (
    <div className="page">
      <h1>בדיקת סיווג פריטים</h1>
      <p>
        <Link to={`/clients/${detail.client_id}`}>← חזרה לדוחות הלקוח</Link>
      </p>
      <p>
        דוח {detail.broker} · שנת מס {detail.tax_year} · {detail.statement.dividends.length} דיבידנדים,{" "}
        {detail.statement.trades.length} רשומות רווח הון, {detail.statement.interest.length} ריבית,{" "}
        {detail.statement.fees.length} עמלות
      </p>

      <section className="card">
        <h2>דיבידנדים וריבית → נספח ד'</h2>
        <table>
          <thead>
            <tr>
              <th>סוג</th>
              <th>פריט</th>
              <th>סכום (מטבע מקור)</th>
              <th>שדה יעד בנספח ד'</th>
              <th>הערה</th>
            </tr>
          </thead>
          <tbody>
            {dividendAndInterestItems.map((item) => {
              const currentField = fieldOverrides[item.source_id] !== undefined ? fieldOverrides[item.source_id] : item.nispach_d_field;
              return (
                <tr key={item.source_id} className={item.needs_review ? "needs-review" : ""}>
                  <td>{SOURCE_KIND_LABELS[item.source_kind]}</td>
                  <td>{item.source_id}</td>
                  <td>{item.amount_source_ccy.toFixed(2)}</td>
                  <td>
                    <select
                      value={currentField ?? ""}
                      onChange={(e) =>
                        setFieldOverrides((prev) => ({ ...prev, [item.source_id]: e.target.value || null }))
                      }
                    >
                      <option value="">לא ממופה - יש לבחור</option>
                      {Object.entries(NISPACH_D_FIELD_LABELS).map(([field, label]) => (
                        <option key={field} value={field}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="reason">{item.review_reason}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h2>רווח הון → נספח ג'</h2>
        <table>
          <thead>
            <tr>
              <th>פריט</th>
              <th>רווח/הפסד (מטבע מקור)</th>
              <th>מדרגת מס</th>
              <th>הערה</th>
            </tr>
          </thead>
          <tbody>
            {tradeItems.map((item) => (
              <tr key={item.source_id} className={item.needs_review ? "needs-review" : ""}>
                <td>{item.source_id}</td>
                <td>{item.amount_source_ccy.toFixed(2)}</td>
                <td>
                  <select
                    value={bracketOverrides[item.source_id] ?? "25"}
                    onChange={(e) => setBracketOverrides((prev) => ({ ...prev, [item.source_id]: e.target.value }))}
                  >
                    {NISPACH_C_BRACKETS.map((b) => (
                      <option key={b} value={b}>
                        {b}%
                      </option>
                    ))}
                  </select>
                </td>
                <td className="reason">{item.review_reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h2>עמלות ודמי ניהול (מידע בלבד, לא ממופה)</h2>
        <table>
          <thead>
            <tr>
              <th>פריט</th>
              <th>סכום (מטבע מקור)</th>
            </tr>
          </thead>
          <tbody>
            {feeItems.map((item) => (
              <tr key={item.source_id}>
                <td>{item.source_id}</td>
                <td>{item.amount_source_ccy.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <div className="row">
        <button disabled={saving} onClick={handleSave}>
          {saving ? "שומר..." : "שמור סיווג"}
        </button>
        <Link to={`/preview/${detail.id}`}>
          <button>המשך להפקת הנספח</button>
        </Link>
      </div>
    </div>
  );
}
