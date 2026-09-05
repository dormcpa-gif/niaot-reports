import { type FormEvent, type ReactNode, useEffect, useState } from "react";

/**
 * Client-side-only screen lock. This is a stopgap until Netlify's own
 * (paid-plan) site password protection is enabled, or the backend gets
 * real server-side auth -- it is NOT real security. Anyone who opens
 * devtools/view-source can read the password and bypass this outright,
 * and the app's actual data still comes from an API with no auth of its
 * own. Don't treat this as protecting real client data by itself.
 */
const SITE_PASSWORD = "311576250";
const SESSION_KEY = "niaot-reports-unlocked";

export default function PasswordGate({ children }: { children: ReactNode }) {
  const [unlocked, setUnlocked] = useState(false);
  const [attempt, setAttempt] = useState("");
  const [error, setError] = useState(false);

  useEffect(() => {
    try {
      if (sessionStorage.getItem(SESSION_KEY) === "1") {
        setUnlocked(true);
      }
    } catch {
      // sessionStorage unavailable (e.g. private browsing) - fall through to the password screen
    }
  }, []);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (attempt === SITE_PASSWORD) {
      setError(false);
      setUnlocked(true);
      try {
        sessionStorage.setItem(SESSION_KEY, "1");
      } catch {
        // ignore storage failures - unlocked state still holds for this page load
      }
    } else {
      setError(true);
    }
  }

  if (unlocked) return <>{children}</>;

  return (
    <div className="page" style={{ maxWidth: 360, marginTop: "15vh" }}>
      <div className="card">
        <h1 style={{ fontSize: 18 }}>כניסה למערכת</h1>
        <form onSubmit={handleSubmit}>
          <div className="row">
            <input
              type="password"
              autoFocus
              placeholder="סיסמה"
              value={attempt}
              onChange={(e) => {
                setAttempt(e.target.value);
                setError(false);
              }}
            />
          </div>
          <button type="submit">כניסה</button>
        </form>
        {error && <p className="error">סיסמה שגויה</p>}
      </div>
    </div>
  );
}
