import { apiPath } from "./derived";
import type { ApiDocument, ApiDocumentListResponse, ApiResult, SessionState } from "./types";

interface ListDocumentsParams {
  limit?: number;
  cursor?: string | null;
  status?: string;
  owner_user_id?: string;
  created_from?: string;
  created_to?: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class ApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly getSession: () => SessionState | null,
  ) {}

  async request<T>(path: string, init: RequestInit & { noAuth?: boolean } = {}): Promise<T> {
    const headers = new Headers(init.headers);
    const session = this.getSession();
    if (!init.noAuth && session?.token) headers.set("Authorization", `Bearer ${session.token}`);

    const response = await fetch(apiPath(this.baseUrl, path), {
      ...init,
      headers,
    });

    if (!response.ok) {
      const body = await response.text().catch(() => "");
      throw new ApiError(body || response.statusText || `HTTP ${response.status}`, response.status);
    }

    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  login(email: string, password: string): Promise<{ access_token: string; token_type: string }> {
    return this.request("/auth/login", {
      method: "POST",
      noAuth: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  }

  me(): Promise<{ id: string; org_id: string; email: string }> {
    return this.request("/auth/me");
  }

  listDocuments(params: ListDocumentsParams = {}): Promise<ApiDocumentListResponse> {
    const query = new URLSearchParams();
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.cursor) query.set("cursor", params.cursor);
    if (params.status && params.status !== "all") query.set("status", params.status);
    if (params.owner_user_id) query.set("owner_user_id", params.owner_user_id);
    if (params.created_from) query.set("created_from", params.created_from);
    if (params.created_to) query.set("created_to", params.created_to);
    const suffix = query.size > 0 ? `?${query.toString()}` : "";
    return this.request(`/documents${suffix}`);
  }

  createDocument(input: { filename: string; content_type: string; size_bytes: number }): Promise<ApiDocument> {
    return this.request("/documents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
  }

  uploadDocument(documentId: string, file: File, filename: string): Promise<unknown> {
    const data = new FormData();
    data.append("file", file, filename);
    return this.request(`/dev/documents/${documentId}/upload`, {
      method: "POST",
      body: data,
    });
  }

  completeUpload(documentId: string): Promise<ApiDocument> {
    return this.request(`/documents/${documentId}/complete-upload`, { method: "POST" });
  }

  getDocument(documentId: string): Promise<ApiDocument> {
    return this.request(`/documents/${documentId}`);
  }

  getResult(documentId: string): Promise<ApiResult> {
    return this.request(`/documents/${documentId}/result`);
  }

  health(): Promise<Response> {
    return fetch(apiPath(this.baseUrl, "/health"));
  }

  signature(body: string): Promise<{ signature: string }> {
    return this.request("/dev/partner-signature", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    });
  }

  sendWebhook(body: string, signature: string): Promise<Response> {
    return fetch(apiPath(this.baseUrl, "/webhooks/partner"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Partner-Signature": signature,
      },
      body,
    });
  }
}
