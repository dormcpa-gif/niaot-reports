import { getToken } from "../auth/tokenStorage";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface Client {
  id: string;
  full_name: string;
  tax_file_number: string | null;
  created_by_name?: string | null;
}

export interface CurrentUser {
  id: string;
  email: string;
  full_name: string;
  role: "admin" | "employee";
}

export interface AdminUser extends CurrentUser {
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface ActivityLogRow {
  id: string;
  user_id: string | null;
  user_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  detail: Record<string, any> | null;
  created_at: string;
}

export interface SourceRef {
  statement_id: string;
  page: number;
  table_name: string;
  row_text: string;
}

export interface ClassifiedItem {
  source_kind: "dividend" | "interest" | "trade" | "fee";
  source_id: string;
  nispach_d_field: string | null;
  amount_source_ccy: number;
  value_date: string;
  withholding_source_ccy: number;
  needs_review: boolean;
  review_reason: string | null;
  // capital-gain lots only
  symbol?: string | null;
  lot_level?: boolean;
  open_date?: string | null;
}

export interface NormalizedStatement {
  statement_id: string;
  broker: string;
  period_start: string;
  period_end: string;
  base_currency: string;
  dividends: unknown[];
  interest: unknown[];
  trades: unknown[];
  fees: unknown[];
  sale_proceeds_by_symbol: Record<string, number>;
}

export interface StatementSummary {
  id: string;
  client_id: string;
  tax_year: number;
  broker: string;
  original_filename: string;
  dividend_count: number;
  interest_count: number;
  trade_count: number;
  fee_count: number;
  needs_review_count: number;
}

export interface InputDocumentInfo {
  filename: string;
  extracted_chars: number;
  extraction_note: string | null;
}

export interface DeepAnalysisResult {
  id: string;
  client_id: string;
  tax_year: number;
  created_at: string;
  model: string;
  input_documents: InputDocumentInfo[];
  narrative: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  structured: Record<string, any> | null;
  structured_parse_error: string | null;
}

export interface DeepAnalysisSummary {
  id: string;
  client_id: string;
  tax_year: number;
  created_at: string;
  input_filenames: string[];
  narrative_excerpt: string;
}

export interface StatementDetail {
  id: string;
  client_id: string;
  tax_year: number;
  broker: string;
  statement: NormalizedStatement;
  classified: ClassifiedItem[];
  overrides: {
    field_overrides?: Record<string, string | null>;
    bracket_overrides?: Record<string, string>;
  };
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) =>
    req<{ token: string; user: CurrentUser }>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),
  logout: () => req<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  getMe: () => req<CurrentUser>("/auth/me"),

  listUsers: () => req<AdminUser[]>("/admin/users"),
  createUser: (full_name: string, email: string, password: string, role: "admin" | "employee") =>
    req<AdminUser>("/admin/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ full_name, email, password, role }),
    }),
  updateUser: (id: string, patch: { role?: "admin" | "employee"; is_active?: boolean }) =>
    req<AdminUser>(`/admin/users/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  resetPassword: (id: string, new_password: string) =>
    req<{ ok: boolean }>(`/admin/users/${id}/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_password }),
    }),
  getActivityLog: (params?: { user_id?: string; action?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.user_id) qs.set("user_id", params.user_id);
    if (params?.action) qs.set("action", params.action);
    if (params?.limit) qs.set("limit", String(params.limit));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return req<ActivityLogRow[]>(`/admin/activity${suffix}`);
  },

  listClients: () => req<Client[]>("/clients"),
  createClient: (full_name: string, tax_file_number: string | null) =>
    req<Client>("/clients", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ full_name, tax_file_number }),
    }),

  uploadStatement: async (
    clientId: string,
    taxYear: number,
    broker: string,
    file: File
  ): Promise<StatementSummary> => {
    const form = new FormData();
    form.append("client_id", clientId);
    form.append("tax_year", String(taxYear));
    form.append("broker", broker);
    form.append("file", file);
    const res = await fetch(`${API_BASE}/statements`, { method: "POST", body: form, headers: authHeaders() });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  getStatement: (id: string) => req<StatementDetail>(`/statements/${id}`),

  listStatementsForClient: (clientId: string) =>
    req<StatementSummary[]>(`/statements/by-client/${clientId}`),

  updateOverrides: (
    id: string,
    fieldOverrides: Record<string, string | null>,
    bracketOverrides: Record<string, string>
  ) =>
    req<StatementDetail>(`/statements/${id}/overrides`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field_overrides: fieldOverrides, bracket_overrides: bracketOverrides }),
    }),

  listDeepAnalysesForClient: (clientId: string) =>
    req<DeepAnalysisSummary[]>(`/analysis/by-client/${clientId}`),

  getDeepAnalysis: (id: string) => req<DeepAnalysisResult>(`/analysis/${id}`),

  createDeepAnalysis: async (
    clientId: string,
    taxYear: number,
    files: File[],
    clientContext: string
  ): Promise<DeepAnalysisResult> => {
    const form = new FormData();
    form.append("client_id", clientId);
    form.append("tax_year", String(taxYear));
    form.append("client_context", clientContext);
    for (const f of files) form.append("files", f);
    const res = await fetch(`${API_BASE}/analysis/deep`, { method: "POST", body: form, headers: authHeaders() });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  downloadAppendix: async (
    id: string,
    fxRates: { currency: string; on_date: string; rate: number }[],
    options: { useBoiRates: boolean; acquisitionDates: Record<string, string> }
  ): Promise<Blob> => {
    const res = await fetch(`${API_BASE}/statements/${id}/appendix.xlsx`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        fx_rates: fxRates,
        use_boi_rates: options.useBoiRates,
        acquisition_dates: options.acquisitionDates,
      }),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.blob();
  },
};
