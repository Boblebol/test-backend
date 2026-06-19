import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

describe("App", () => {
  let storage: Record<string, string>;

  beforeEach(() => {
    storage = {};
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        clear: () => {
          storage = {};
        },
        getItem: (key: string) => storage[key] ?? null,
        removeItem: (key: string) => {
          delete storage[key];
        },
        setItem: (key: string, value: string) => {
          storage[key] = value;
        },
      },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("renders the Primmo login screen with demo accounts and proxied API base", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Connexion" })).toBeInTheDocument();
    expect(screen.getByText("Primmo Alpha")).toBeInTheDocument();
    expect(screen.getByText("Primmo Beta")).toBeInTheDocument();
    expect(screen.getByDisplayValue("/api")).toBeInTheDocument();
  });

  it("does not render a front admin panel for authenticated users", async () => {
    window.localStorage.setItem(
      "primmo_sessions",
      JSON.stringify({
        alpha: {
          token: "token",
          email: "alpha@example.com",
          orgId: "org-alpha",
          label: "Primmo Alpha",
        },
      }),
    );
    window.localStorage.setItem("primmo_active", "alpha");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ items: [], next_cursor: null }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Documents" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Test console/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Simulateur de webhook partenaire")).not.toBeInTheDocument();
  });
});
