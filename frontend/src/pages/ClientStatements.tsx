import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Client, type StatementSummary } from "../api/client";

export default function ClientStatements() {
  const { clientId } = useParams<{ clientId: string }>();
  const [client, setClient] = useState<Client | null>(null);
  const [statements, setStatements] = useState<StatementSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!clientId) return;
    Promise.all([api.listClients(), api.listStatementsForClient(clientId)])
      .then(([clients, stmts]) => {
        setClient(clients.find((c) => c.id === clientId) ?? null);
        setStatements(stmts);
      })
      .catch((e) => setError(String(e)));
  }, [clientId]);

  if (error) return <p className="error">{error}</p>;

  return (
    <div className="page">
      <h1>דוחות של {client ? client.full_name : "..."}</h1>
      {client?.tax_file_number && <p className="hint">מספר תיק: {client.tax_file_number}</p>}

      {statements.length === 0 && <p>אין עדיין דוחות עבור לקוח זה.</p>}

      {statements.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>שנת מס</th>
              <th>ברוקר</th>
              <th>קובץ מקור</th>
              <th>דיבידנדים</th>
              <th>רווח הון</th>
              <th>ריבית</th>
              <th>עמלות</th>
              <th>דורש אימות</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {statements.map((s) => (
              <tr key={s.id} className={s.needs_review_count > 0 ? "needs-review" : ""}>
                <td>{s.tax_year}</td>
                <td>{s.broker}</td>
                <td>{s.original_filename}</td>
                <td>{s.dividend_count}</td>
                <td>{s.trade_count}</td>
                <td>{s.interest_count}</td>
                <td>{s.fee_count}</td>
                <td>{s.needs_review_count}</td>
                <td>
                  <Link to={`/review/${s.id}`}>בדיקת סיווג</Link>
                  {" · "}
                  <Link to={`/preview/${s.id}`}>הפקת נספח</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="row">
        <Link to="/">
          <button>העלה דוח נוסף</button>
        </Link>
      </div>
    </div>
  );
}
