import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "./api";

describe("ApiClient", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("passes document pagination and filter parameters to the backend", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ items: [], next_cursor: null }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const client = new ApiClient("/api", () => ({
      token: "token",
      email: "alpha@example.com",
      orgId: "org-alpha",
      label: "Primmo Alpha",
    }));

    const response = await client.listDocuments({
      limit: 25,
      status: "ready",
      cursor: "cursor value",
    });

    expect(response).toEqual({ items: [], next_cursor: null });
    const [url, init] = fetchMock.mock.calls[0];
    const query = String(url).split("?")[1];
    expect(String(url)).toMatch(/^\/api\/documents\?/);
    expect(new URLSearchParams(query).get("limit")).toBe("25");
    expect(new URLSearchParams(query).get("status")).toBe("ready");
    expect(new URLSearchParams(query).get("cursor")).toBe("cursor value");
    expect((init?.headers as Headers).get("Authorization")).toBe("Bearer token");
  });
});
