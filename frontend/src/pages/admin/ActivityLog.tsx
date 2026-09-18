import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type ActivityLogRow, type AdminUser } from "../../api/client";

export default function ActivityLog() {
  const [rows, setRows] = useState<ActivityLogRow[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [userFilter, setUserFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listUsers().then(setUsers).catch(() => setUsers([]));
  }, []);

  function refresh() {
    api
      .getActivityLog({ user_id: userFilter || undefined, action: actionFilter || undefined, limit: 300 })
      .then(setRows)
      .catch((e) => setError(String(e)));
  }

  useEffect(refresh, [userFilter, actionFilter]);

  const actionOptions = Array.from(new Set(rows.map((r) => r.action))).sort();

  return (
    <div className="page">
      <h1>לוג פעילות</h1>
      <p>
        <Link to="/admin/users">← ניהול משתמשים</Link>
      </p>

      <section className="card">
        <div className="row">
          <label>
            סינון לפי משתמש
            <select value={userFilter} onChange={(e) => setUserFilter(e.target.value)}>
              <option value="">הכל</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name} ({u.email})
                </option>
              ))}
            </select>
          </label>
          <label>
            סינון לפי פעולה
            <select value={actionFilter} onChange={(e) => setActionFilter(e.target.value)}>
              <option value="">הכל</option>
              {actionOptions.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </label>
        </div>
        {error && <p className="error">{error}</p>}
        <table>
          <thead>
            <tr>
              <th>מתי</th>
              <th>משתמש</th>
              <th>פעולה</th>
              <th>יעד</th>
              <th>פרטים</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{new Date(r.created_at).toLocaleString("he-IL")}</td>
                <td>{r.user_email ?? "-"}</td>
                <td>{r.action}</td>
                <td>{r.target_type ? `${r.target_type} ${r.target_id ?? ""}` : ""}</td>
                <td className="reason">{r.detail ? JSON.stringify(r.detail) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
