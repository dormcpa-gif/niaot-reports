import { type FormEvent, useState } from "react";
import { useAuth } from "../auth/AuthContext";

export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
    } catch {
      setError("אימייל או סיסמה שגויים");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page" style={{ maxWidth: 360, marginTop: "15vh" }}>
      <div className="card">
        <h1 style={{ fontSize: 18 }}>כניסה למערכת</h1>
        <form onSubmit={handleSubmit}>
          <div className="row">
            <input
              type="email"
              autoFocus
              placeholder="אימייל"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={{ width: "100%" }}
            />
          </div>
          <div className="row">
            <input
              type="password"
              placeholder="סיסמה"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{ width: "100%" }}
            />
          </div>
          <button type="submit" disabled={busy}>
            {busy ? "מתחבר..." : "כניסה"}
          </button>
        </form>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  );
}
