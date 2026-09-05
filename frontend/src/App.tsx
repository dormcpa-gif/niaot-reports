import { Link, Route, BrowserRouter, Routes } from "react-router-dom";
import PasswordGate from "./components/PasswordGate";
import AppendixPreview from "./pages/AppendixPreview";
import ClientStatements from "./pages/ClientStatements";
import ClientsIndex from "./pages/ClientsIndex";
import ReviewTransactions from "./pages/ReviewTransactions";
import UploadStatement from "./pages/UploadStatement";

export default function App() {
  return (
    <PasswordGate>
      <AppRoutes />
    </PasswordGate>
  );
}

function AppRoutes() {
  return (
    <BrowserRouter>
      <header className="app-header">
        <h1>מערכת דוחות ני״ע - IBKR ← נספח ג'/ד'</h1>
        <nav>
          <Link to="/">העלאת דוח</Link>
          {" · "}
          <Link to="/clients">לקוחות</Link>
        </nav>
      </header>
      <Routes>
        <Route path="/" element={<UploadStatement />} />
        <Route path="/clients" element={<ClientsIndex />} />
        <Route path="/clients/:clientId" element={<ClientStatements />} />
        <Route path="/review/:statementId" element={<ReviewTransactions />} />
        <Route path="/preview/:statementId" element={<AppendixPreview />} />
      </Routes>
    </BrowserRouter>
  );
}
