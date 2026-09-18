import { Link, Route, BrowserRouter, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import AppendixPreview from "./pages/AppendixPreview";
import ClientStatements from "./pages/ClientStatements";
import ClientsIndex from "./pages/ClientsIndex";
import DeepAnalysisResultPage from "./pages/DeepAnalysisResult";
import DeepAnalysisUpload from "./pages/DeepAnalysisUpload";
import Login from "./pages/Login";
import ReviewTransactions from "./pages/ReviewTransactions";
import UploadStatement from "./pages/UploadStatement";
import ActivityLog from "./pages/admin/ActivityLog";
import UsersAdmin from "./pages/admin/UsersAdmin";

export default function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  );
}

function Gate() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Login />;
  return <AppRoutes />;
}

function AppRoutes() {
  const { user, logout } = useAuth();

  return (
    <BrowserRouter>
      <header className="app-header">
        <h1>מערכת דוחות ני״ע - IBKR ← נספח ג'/ד'</h1>
        <nav>
          <Link to="/">העלאת דוח</Link>
          {" · "}
          <Link to="/clients">לקוחות</Link>
          {" · "}
          <Link to="/analysis">ניתוח מעמיק (AI)</Link>
          {user?.role === "admin" && (
            <>
              {" · "}
              <Link to="/admin/users">ניהול</Link>
            </>
          )}
          {"    "}
          <span style={{ float: "left", fontSize: 13 }}>
            שלום {user?.full_name} ·{" "}
            <a href="#" onClick={(e) => { e.preventDefault(); logout(); }}>
              התנתקות
            </a>
          </span>
        </nav>
      </header>
      <Routes>
        <Route path="/" element={<UploadStatement />} />
        <Route path="/clients" element={<ClientsIndex />} />
        <Route path="/clients/:clientId" element={<ClientStatements />} />
        <Route path="/review/:statementId" element={<ReviewTransactions />} />
        <Route path="/preview/:statementId" element={<AppendixPreview />} />
        <Route path="/analysis" element={<DeepAnalysisUpload />} />
        <Route path="/analysis/:analysisId" element={<DeepAnalysisResultPage />} />
        {user?.role === "admin" && (
          <>
            <Route path="/admin/users" element={<UsersAdmin />} />
            <Route path="/admin/activity" element={<ActivityLog />} />
          </>
        )}
      </Routes>
    </BrowserRouter>
  );
}
