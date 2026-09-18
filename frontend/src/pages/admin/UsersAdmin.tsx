import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AdminUser } from "../../api/client";

export default function UsersAdmin() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"admin" | "employee">("employee");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function refresh() {
    api.listUsers().then(setUsers).catch((e) => setError(String(e)));
  }

  useEffect(refresh, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.createUser(fullName, email, password, role);
      setFullName("");
      setEmail("");
      setPassword("");
      setRole("employee");
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(u: AdminUser) {
    setError(null);
    try {
      await api.updateUser(u.id, { is_active: !u.is_active });
      refresh();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleResetPassword(u: AdminUser) {
    const newPassword = window.prompt(`סיסמה חדשה עבור ${u.full_name}:`);
    if (!newPassword) return;
    setError(null);
    try {
      await api.resetPassword(u.id, newPassword);
      window.alert("הסיסמה עודכנה.");
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="page">
      <h1>ניהול משתמשים</h1>
      <p>
        <Link to="/admin/activity">לוג פעילות ←</Link>
      </p>

      <section className="card">
        <h2>הוספת משתמש</h2>
        <form onSubmit={handleCreate}>
          <div className="row">
            <input placeholder="שם מלא" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
            <input
              type="email"
              placeholder="אימייל"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            <input
              type="password"
              placeholder="סיסמה"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <select value={role} onChange={(e) => setRole(e.target.value as "admin" | "employee")}>
              <option value="employee">עובד</option>
              <option value="admin">מנהל</option>
            </select>
            <button type="submit" disabled={busy}>
              {busy ? "יוצר..." : "צור משתמש"}
            </button>
          </div>
        </form>
        {error && <p className="error">{error}</p>}
      </section>

      <section className="card">
        <h2>משתמשים קיימים</h2>
        <table>
          <thead>
            <tr>
              <th>שם</th>
              <th>אימייל</th>
              <th>תפקיד</th>
              <th>סטטוס</th>
              <th>כניסה אחרונה</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className={!u.is_active ? "needs-review" : ""}>
                <td>{u.full_name}</td>
                <td>{u.email}</td>
                <td>{u.role === "admin" ? "מנהל" : "עובד"}</td>
                <td>{u.is_active ? "פעיל" : "מושבת"}</td>
                <td>{u.last_login_at ? new Date(u.last_login_at).toLocaleString("he-IL") : "טרם התחבר/ה"}</td>
                <td>
                  <button onClick={() => toggleActive(u)}>{u.is_active ? "השבת" : "הפעל"}</button>{" "}
                  <button onClick={() => handleResetPassword(u)}>אפס סיסמה</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
