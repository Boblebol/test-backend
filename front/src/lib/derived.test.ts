import { describe, expect, it } from "vitest";
import { deriveStepStatuses, parseSseChunk, resolveLinks } from "./derived";

describe("deriveStepStatuses", () => {
  it("marks every pipeline step successful when a document is ready", () => {
    expect(deriveStepStatuses("ready")).toEqual({
      ocr: "success",
      metadata: "success",
      chunking: "success",
      external_call: "success",
      partner_webhook: "success",
    });
  });

  it("keeps the webhook step waiting when the partner callback is pending", () => {
    expect(deriveStepStatuses("waiting_partner")).toEqual({
      ocr: "success",
      metadata: "success",
      chunking: "success",
      external_call: "success",
      partner_webhook: "waiting_webhook",
    });
  });

  it("uses explicit step statuses when a partner webhook failure makes the document failed", () => {
    expect(
      deriveStepStatuses("failed", {
        ocr: "success",
        metadata: "success",
        chunking: "success",
        external_call: "success",
        partner_webhook: "failed",
      }),
    ).toEqual({
      ocr: "success",
      metadata: "success",
      chunking: "success",
      external_call: "success",
      partner_webhook: "failed",
    });
  });
});

describe("parseSseChunk", () => {
  it("extracts event type and JSON payload from a server-sent event chunk", () => {
    expect(
      parseSseChunk(
        'event: progress\ndata: {"step":"ocr","step_status":"running","document_status":"processing"}',
      ),
    ).toEqual({
      type: "progress",
      data: {
        step: "ocr",
        step_status: "running",
        document_status: "processing",
      },
    });
  });

  it("returns null for keep-alive comments", () => {
    expect(parseSseChunk(": keep-alive")).toBeNull();
  });
});

describe("resolveLinks", () => {
  it("builds direct docs links when the app API base is proxied", () => {
    expect(resolveLinks("/api", "http://127.0.0.1:5173")).toEqual({
      swagger: "http://127.0.0.1:8000/docs",
      openapi: "http://127.0.0.1:8000/openapi.json",
      flask: "http://127.0.0.1:8001",
      minio: "http://127.0.0.1:9001",
    });
  });
});
