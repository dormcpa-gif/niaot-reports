import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Client } from "../api/client";

export default function ClientsIndex() {
  const [clients, setClients] = useState<Client[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listClients().then(setClients).catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="error">{error}</p>;

  return (
    <div className="page">
      <h1>לקוחות</h1>
      {clients.length === 0 && <p>אין עדיין לקוחות. ניתן ליצור לקוח חדש במסך ההעלאה.</p>}
      <table>
        <thead>
          <tr>
            <th>שם</th>
            <th>מספר תיק</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {clients.map((c) => (
            <tr key={c.id}>
              <td>{c.full_name}</td>
              <td>{c.tax_file_number ?? ""}</td>
              <td>
                <Link to={`/clients/${c.id}`}>דוחות הלקוח</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
