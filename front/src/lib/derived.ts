import { STEP_DEFS } from "./constants";
import type {
  ApiDocument,
  DocumentStatus,
  ParsedSseEvent,
  ProcessingStepStatus,
  StepStatusMap,
  UsefulLinks,
} from "./types";

const DEFAULT_STEPS: StepStatusMap = {
  ocr: "pending",
  metadata: "pending",
  chunking: "pending",
  external_call: "pending",
  partner_webhook: "pending",
};

export function pick<T = unknown>(source: Record<string, unknown> | null | undefined, ...keys: string[]): T | undefined {
  if (!source) return undefined;
  for (const key of keys) {
    const value = source[key];
    if (value !== undefined && value !== null && value !== "") return value as T;
  }
  return undefined;
}

export function normalizeBaseUrl(baseUrl: string): string {
  const trimmed = baseUrl.trim();
  if (!trimmed) return "/api";
  return trimmed.length > 1 ? trimmed.replace(/\/+$/, "") : trimmed;
}

export function apiPath(baseUrl: string, path: string): string {
  const base = normalizeBaseUrl(baseUrl);
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${base}${suffix}`;
}

export function deriveStepStatuses(
  status: DocumentStatus | undefined,
  explicitSteps?: ApiDocument["pipeline_steps"] | ApiDocument["steps"] | ApiDocument["step_statuses"] | null,
): StepStatusMap {
  const explicit = explicitSteps && typeof explicitSteps === "object" ? explicitSteps : null;
  if (explicit) {
    return STEP_DEFS.reduce<StepStatusMap>(
      (acc, step) => {
        acc[step.key] = explicit[step.key] ?? acc[step.key];
        return acc;
      },
      { ...DEFAULT_STEPS },
    );
  }

  const steps = { ...DEFAULT_STEPS };
  if (status === "ready") {
    STEP_DEFS.forEach((step) => {
      steps[step.key] = "success";
    });
    return steps;
  }
  if (status === "waiting_partner") {
    steps.ocr = "success";
    steps.metadata = "success";
    steps.chunking = "success";
    steps.external_call = "success";
    steps.partner_webhook = "waiting_webhook";
    return steps;
  }
  if (status === "processing") {
    steps.ocr = "running";
  }
  if (status === "failed") {
    steps.ocr = "failed";
  }
  return steps;
}

export function parseSseChunk(chunk: string): ParsedSseEvent | null {
  const lines = chunk.split(/\r?\n/);
  let type = "message";
  let data = "";

  for (const line of lines) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) type = line.slice("event:".length).trim();
    if (line.startsWith("data:")) data += line.slice("data:".length).trim();
  }

  if (!data) return null;

  try {
    return { type, data: JSON.parse(data) };
  } catch {
    return null;
  }
}

export function resolveLinks(baseUrl: string, origin = window.location.origin): UsefulLinks {
  const base = normalizeBaseUrl(baseUrl);
  if (base.startsWith("/")) {
    const hostUrl = new URL(origin);
    const localApiOrigin = `${hostUrl.protocol}//${hostUrl.hostname}:8000`;
    return {
      swagger: `${localApiOrigin}/docs`,
      openapi: `${localApiOrigin}/openapi.json`,
      flask: `${hostUrl.protocol}//${hostUrl.hostname}:8001`,
      minio: `${hostUrl.protocol}//${hostUrl.hostname}:9001`,
    };
  }

  try {
    const url = new URL(base);
    return {
      swagger: `${base}/docs`,
      openapi: `${base}/openapi.json`,
      flask: `${url.protocol}//${url.hostname}:8001`,
      minio: `${url.protocol}//${url.hostname}:9001`,
    };
  } catch {
    return {
      swagger: `${base}/docs`,
      openapi: `${base}/openapi.json`,
      flask: base,
      minio: base,
    };
  }
}

export function baseHost(baseUrl: string): string {
  const base = normalizeBaseUrl(baseUrl);
  if (base.startsWith("/")) return base;
  try {
    return new URL(base).host;
  } catch {
    return base.replace(/^https?:\/\//, "");
  }
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return `${date.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" })} ${date.toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatSize(bytes: number | null | undefined): string {
  if (bytes === undefined || bytes === null) return "";
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} Ko`;
  return `${(bytes / 1024 / 1024).toFixed(1)} Mo`;
}

export function stepIconClass(status: ProcessingStepStatus, fallbackIcon: string): string {
  if (status === "success") return "ph ph-check";
  if (status === "failed") return "ph ph-x";
  if (status === "waiting_webhook") return "ph ph-hourglass-medium";
  if (status === "running" || status === "retrying") return "ph ph-circle-notch";
  return `ph ${fallbackIcon}`;
}
