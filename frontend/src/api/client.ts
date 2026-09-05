import { getApiKey } from "../components/PasswordGate";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

function authHeaders(): Record<string, string> {
  const key = getApiKey();
  return key ? { "X-API-Key": key } : {};
}

export interface Client {
  id: string;
  full_name: string;
  tax_file_number: string | null;
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

  downloadAppendix: async (
    id: string,
    fxRates: { currency: string; on_date: string; rate: number }[]
  ): Promise<Blob> => {
    const res = await fetch(`${API_BASE}/statements/${id}/appendix.xlsx`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ fx_rates: fxRates }),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.blob();
  },
};
