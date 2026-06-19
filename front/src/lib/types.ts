export type AccountKey = "alpha" | "beta";

export type DocumentStatus =
  | "waiting_upload"
  | "uploaded"
  | "processing"
  | "waiting_partner"
  | "ready"
  | "failed"
  | string;

export type ProcessingStepKey =
  | "ocr"
  | "metadata"
  | "chunking"
  | "external_call"
  | "partner_webhook";

export type ProcessingStepStatus =
  | "pending"
  | "running"
  | "retrying"
  | "success"
  | "waiting_webhook"
  | "failed"
  | "skipped";

export type StepStatusMap = Record<ProcessingStepKey, ProcessingStepStatus>;

export interface DemoAccount {
  key: AccountKey;
  label: string;
  short: string;
  email: string;
  password: string;
  tint: string;
  initials: string;
}

export interface SessionState {
  token: string;
  email: string;
  orgId: string;
  label: string;
}

export interface ApiDocument {
  id?: string;
  document_id?: string;
  org_id?: string;
  owner_user_id?: string;
  original_filename?: string;
  filename?: string;
  name?: string;
  content_type?: string;
  size_bytes?: number;
  status?: DocumentStatus;
  document_status?: DocumentStatus;
  external_job_id?: string | null;
  current_error_type?: string | null;
  current_error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  pipeline_steps?: Partial<Record<ProcessingStepKey, ProcessingStepStatus>>;
  steps?: Partial<Record<ProcessingStepKey, ProcessingStepStatus>>;
  step_statuses?: Partial<Record<ProcessingStepKey, ProcessingStepStatus>>;
}

export interface ApiDocumentListResponse {
  items: ApiDocument[];
  next_cursor: string | null;
}

export interface ApiResult {
  document_id: string;
  ocr_text?: string | null;
  metadata_json?: Record<string, unknown> | null;
  chunks_json?: string[] | null;
  partner_result_json?: Record<string, unknown> | null;
}

export interface ProgressEventPayload {
  org_id?: string;
  document_id?: string;
  step?: ProcessingStepKey;
  step_status?: ProcessingStepStatus;
  document_status?: DocumentStatus;
  occurred_at?: string;
}

export interface ParsedSseEvent {
  type: string;
  data: ProgressEventPayload;
}

export interface UsefulLinks {
  swagger: string;
  openapi: string;
  flask: string;
  minio: string;
}
