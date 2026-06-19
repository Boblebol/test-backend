import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ACCOUNTS, DEFAULT_API_BASE, DOCUMENT_STATUS_META, GUIDE_STEPS, STEP_DEFS, STEP_STATUS_META } from "./lib/constants";
import { ApiClient, ApiError } from "./lib/api";
import {
  apiPath,
  baseHost,
  deriveStepStatuses,
  formatDate,
  formatSize,
  formatTime,
  normalizeBaseUrl,
  parseSseChunk,
  pick,
  resolveLinks,
  stepIconClass,
} from "./lib/derived";
import type {
  AccountKey,
  ApiDocument,
  ApiResult,
  DocumentStatus,
  ProcessingStepKey,
  ProcessingStepStatus,
  ProgressEventPayload,
  SessionState,
  StepStatusMap,
} from "./lib/types";

type ViewName = "login" | "documents" | "detail";
type CreateStepName = "create" | "upload" | "complete";
type CreateStepStatus = "idle" | "running" | "success" | "failed";
type CreateStepState = Record<CreateStepName, CreateStepStatus>;

interface UiEvent {
  t: string;
  type: string;
  step?: ProcessingStepKey;
  stepStatus?: ProcessingStepStatus;
  docStatus?: DocumentStatus;
}

const LOGO_URL =
  "https://cdn.prod.website-files.com/6842cb997217e4a049eb510e/6847ee8a1a7dbf8dca7bf60a_Primmo%20(2).png";

const initialCreateSteps: CreateStepState = {
  create: "idle",
  upload: "idle",
  complete: "idle",
};

function getDocumentId(document: ApiDocument | null | undefined): string {
  return pick<string>(document as Record<string, unknown>, "document_id", "id") ?? "";
}

function getDocumentStatus(document: ApiDocument | null | undefined): DocumentStatus {
  return pick<DocumentStatus>(document as Record<string, unknown>, "document_status", "status") ?? "";
}

function getFilename(document: ApiDocument | null | undefined): string {
  return pick<string>(document as Record<string, unknown>, "original_filename", "filename", "name") ?? "—";
}

function statusMeta(status: DocumentStatus | undefined) {
  return DOCUMENT_STATUS_META[String(status || "")] ?? {
    label: status || "—",
    color: "#6B7280",
    bg: "rgba(97,113,134,.10)",
  };
}

function stepStatusMeta(status: ProcessingStepStatus | undefined) {
  return STEP_STATUS_META[status || "pending"] ?? STEP_STATUS_META.pending;
}

function shortId(value: string | undefined | null): string {
  if (!value) return "—";
  return value.length > 12 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

function storageGet(key: string): string | null {
  try {
    return window.localStorage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string): void {
  try {
    window.localStorage?.setItem(key, value);
  } catch {
    // Storage can be disabled in tests or hardened browser contexts.
  }
}

function storageRemove(key: string): void {
  try {
    window.localStorage?.removeItem(key);
  } catch {
    // Storage can be disabled in tests or hardened browser contexts.
  }
}

function App() {
  const [baseUrl, setBaseUrl] = useState(DEFAULT_API_BASE);
  const [view, setView] = useState<ViewName>("login");
  const [hydrated, setHydrated] = useState(false);
  const [sessions, setSessions] = useState<Partial<Record<AccountKey, SessionState>>>({});
  const [activeAccount, setActiveAccount] = useState<AccountKey | null>(null);
  const [loginAccount, setLoginAccount] = useState<AccountKey>("alpha");
  const [loginEmail, setLoginEmail] = useState(ACCOUNTS.alpha.email);
  const [loginPassword, setLoginPassword] = useState(ACCOUNTS.alpha.password);
  const [loginError, setLoginError] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [orgMenuOpen, setOrgMenuOpen] = useState(false);
  const [showGuide, setShowGuide] = useState(false);

  const [documents, setDocuments] = useState<ApiDocument[]>([]);
  const [nextDocumentsCursor, setNextDocumentsCursor] = useState<string | null>(null);
  const [docsLoading, setDocsLoading] = useState(false);
  const [docsError, setDocsError] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const [detail, setDetail] = useState<ApiDocument | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [result, setResult] = useState<ApiResult | null>(null);
  const [events, setEvents] = useState<UiEvent[]>([]);
  const [stepStatus, setStepStatus] = useState<StepStatusMap>(() => deriveStepStatuses(""));
  const [docStatus, setDocStatus] = useState<DocumentStatus>("");
  const [streamMode, setStreamMode] = useState<"idle" | "connecting" | "sse" | "polling">("idle");
  const [selectedId, setSelectedId] = useState("");

  const [createOpen, setCreateOpen] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState("");
  const [createFilename, setCreateFilename] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [createSteps, setCreateSteps] = useState<CreateStepState>(initialCreateSteps);

  const streamController = useRef<AbortController | null>(null);
  const pollTimer = useRef<number | null>(null);
  const activeSession = activeAccount ? sessions[activeAccount] ?? null : null;
  const activeDef = activeAccount ? ACCOUNTS[activeAccount] : ACCOUNTS.alpha;
  const links = useMemo(() => resolveLinks(baseUrl), [baseUrl]);

  const client = useMemo(
    () =>
      new ApiClient(baseUrl, () => {
        if (!activeAccount) return null;
        return sessions[activeAccount] ?? null;
      }),
    [activeAccount, baseUrl, sessions],
  );

  const stopStream = useCallback(() => {
    if (streamController.current) {
      streamController.current.abort();
      streamController.current = null;
    }
    if (pollTimer.current) {
      window.clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
    setStreamMode("idle");
  }, []);

  const logout = useCallback(() => {
    stopStream();
    storageRemove("primmo_sessions");
    storageRemove("primmo_active");
    setSessions({});
    setActiveAccount(null);
    setView("login");
    setDocuments([]);
    setNextDocumentsCursor(null);
    setDetail(null);
    setResult(null);
    setEvents([]);
    setStepStatus(deriveStepStatuses(""));
  }, [stopStream]);

  const loadResult = useCallback(
    async (id: string) => {
      try {
        const loaded = await client.getResult(id);
        setResult(loaded);
      } catch {
        setResult(null);
      }
    },
    [client],
  );

  const applyProgressEvent = useCallback(
    (type: string, data: ProgressEventPayload) => {
      const nextEvent: UiEvent = {
        t: data.occurred_at || new Date().toISOString(),
        type,
        step: data.step,
        stepStatus: data.step_status,
        docStatus: data.document_status,
      };

      setEvents((current) => [...current, nextEvent].slice(-120));
      if (data.step && data.step_status) {
        setStepStatus((current) => ({ ...current, [data.step!]: data.step_status! }));
      }
      if (data.document_status) {
        setDocStatus(data.document_status);
        setDetail((current) => (current ? { ...current, status: data.document_status } : current));
        if (data.document_status === "ready" && selectedId) void loadResult(selectedId);
      }
    },
    [loadResult, selectedId],
  );

  const startPolling = useCallback(
    (id: string) => {
      setStreamMode("polling");
      if (pollTimer.current) window.clearInterval(pollTimer.current);
      pollTimer.current = window.setInterval(() => {
        void client.getDocument(id).then((loaded) => {
          const status = getDocumentStatus(loaded);
          setDetail(loaded);
          setDocStatus(status);
          setStepStatus((current) =>
            Object.values(current).some((value) => value !== "pending")
              ? current
              : deriveStepStatuses(status, loaded.pipeline_steps ?? loaded.steps ?? loaded.step_statuses),
          );
          if (status === "ready") void loadResult(id);
        });
      }, 2000);
    },
    [client, loadResult],
  );

  const startStream = useCallback(
    async (id: string) => {
      stopStream();
      const controller = new AbortController();
      streamController.current = controller;
      setStreamMode("connecting");
      try {
        const response = await fetch(apiPath(baseUrl, `/documents/${id}/events`), {
          headers: activeSession?.token ? { Authorization: `Bearer ${activeSession.token}` } : {},
          signal: controller.signal,
        });
        if (!response.ok || !response.body) throw new Error("stream unavailable");

        setStreamMode("sse");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let index = buffer.indexOf("\n\n");
          while (index >= 0) {
            const chunk = buffer.slice(0, index);
            buffer = buffer.slice(index + 2);
            const parsed = parseSseChunk(chunk);
            if (parsed) applyProgressEvent(parsed.type, parsed.data);
            index = buffer.indexOf("\n\n");
          }
        }
        setStreamMode("idle");
      } catch (error) {
        if ((error as Error).name !== "AbortError") startPolling(id);
      }
    },
    [activeSession?.token, applyProgressEvent, baseUrl, startPolling, stopStream],
  );

  const loadDetail = useCallback(
    async (id: string, initial = false) => {
      setDetailLoading(true);
      setDetailError("");
      try {
        const loaded = await client.getDocument(id);
        const status = getDocumentStatus(loaded);
        setDetail(loaded);
        setDocStatus(status);
        setDetailLoading(false);
        setStepStatus((current) =>
          initial || Object.values(current).every((value) => value === "pending")
            ? deriveStepStatuses(status, loaded.pipeline_steps ?? loaded.steps ?? loaded.step_statuses)
            : current,
        );
        if (status === "ready") void loadResult(id);
        if (initial) void startStream(id);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          logout();
          return;
        }
        setDetailLoading(false);
        setDetailError(error instanceof ApiError ? `Erreur ${error.status}` : networkError(baseUrl));
      }
    },
    [baseUrl, client, loadResult, logout, startStream],
  );

  const loadDocuments = useCallback(async (cursor?: string | null) => {
    if (!activeAccount) return;
    setDocsLoading(true);
    setDocsError("");
    try {
      const loaded = await client.listDocuments({
        limit: 50,
        status: statusFilter,
        cursor,
      });
      setDocuments((current) => (cursor ? [...current, ...loaded.items] : loaded.items));
      setNextDocumentsCursor(loaded.next_cursor);
      setDocsLoading(false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        logout();
        return;
      }
      setDocsLoading(false);
      setDocsError(error instanceof ApiError ? `Erreur ${error.status} lors du chargement.` : networkError(baseUrl));
    }
  }, [activeAccount, baseUrl, client, logout, statusFilter]);

  useEffect(() => {
    try {
      const storedBase = storageGet("primmo_base");
      const storedSessions = storageGet("primmo_sessions");
      const storedActive = storageGet("primmo_active") as AccountKey | null;
      if (storedBase) setBaseUrl(storedBase);
      if (storedSessions) {
        const parsed = JSON.parse(storedSessions) as Partial<Record<AccountKey, SessionState>>;
        const keys = Object.keys(parsed) as AccountKey[];
        if (keys.length) {
          setSessions(parsed);
          setActiveAccount(storedActive && parsed[storedActive] ? storedActive : keys[0]);
          setView("documents");
        }
      }
    } catch {
      storageRemove("primmo_sessions");
    } finally {
      setHydrated(true);
    }
  }, []);

  useEffect(() => {
    storageSet("primmo_base", baseUrl);
  }, [baseUrl]);

  useEffect(() => {
    if (Object.keys(sessions).length) storageSet("primmo_sessions", JSON.stringify(sessions));
  }, [sessions]);

  useEffect(() => {
    if (activeAccount) storageSet("primmo_active", activeAccount);
  }, [activeAccount]);

  useEffect(() => {
    if (hydrated && view === "documents" && activeAccount) void loadDocuments();
  }, [activeAccount, hydrated, loadDocuments, view]);

  useEffect(() => () => stopStream(), [stopStream]);

  async function loginWith(account: AccountKey, email: string, password: string, keepOnLogin = true) {
    setLoginBusy(true);
    setLoginError("");
    try {
      const login = await client.login(email, password);
      const meResponse = await fetch(apiPath(baseUrl, "/auth/me"), {
        headers: { Authorization: `Bearer ${login.access_token}` },
      });
      const me = meResponse.ok ? ((await meResponse.json()) as { email?: string; org_id?: string }) : {};
      const accountDef = ACCOUNTS[account];
      setSessions((current) => ({
        ...current,
        [account]: {
          token: login.access_token,
          email: me.email || email,
          orgId: me.org_id || "",
          label: accountDef.label,
        },
      }));
      setActiveAccount(account);
      setLoginBusy(false);
      if (keepOnLogin) setView("documents");
    } catch (error) {
      setLoginBusy(false);
      if (error instanceof ApiError && error.status === 401) {
        setLoginError("Identifiants invalides.");
      } else {
        setLoginError(networkError(baseUrl));
      }
    }
  }

  function pickLoginAccount(account: AccountKey) {
    const accountDef = ACCOUNTS[account];
    setLoginAccount(account);
    setLoginEmail(accountDef.email);
    setLoginPassword(accountDef.password);
  }

  function switchAccount(account: AccountKey) {
    setOrgMenuOpen(false);
    if (activeAccount === account) return;
    stopStream();
    setResult(null);
    setEvents([]);
    setDetail(null);
    setDocuments([]);
    setNextDocumentsCursor(null);
    setSelectedId("");
    setStepStatus(deriveStepStatuses(""));
    if (sessions[account]) {
      setActiveAccount(account);
      setView("documents");
      return;
    }
    const accountDef = ACCOUNTS[account];
    void loginWith(account, accountDef.email, accountDef.password);
  }

  function navDocuments() {
    stopStream();
    setView("documents");
    setOrgMenuOpen(false);
    void loadDocuments();
  }

  function openDetail(id: string) {
    stopStream();
    setView("detail");
    setSelectedId(id);
    setDetail(null);
    setResult(null);
    setEvents([]);
    setStepStatus(deriveStepStatuses(""));
    void loadDetail(id, true);
  }

  function openCreate() {
    setSelectedFile(null);
    setCreateOpen(true);
    setCreateBusy(false);
    setCreateError("");
    setCreateFilename("");
    setCreateSteps(initialCreateSteps);
  }

  function changeStatusFilter(status: string) {
    if (status === statusFilter) return;
    setDocuments([]);
    setNextDocumentsCursor(null);
    setStatusFilter(status);
  }

  function onFilePick(fileList: FileList | null) {
    const file = fileList?.[0];
    if (!file) return;
    const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
    setSelectedFile(file);
    setCreateFilename(file.name);
    setCreateError(isPdf ? "" : "Le fichier doit être un PDF.");
  }

  async function runCreate() {
    if (!selectedFile) {
      setCreateError("Sélectionnez un fichier PDF.");
      return;
    }
    const isPdf = selectedFile.type === "application/pdf" || /\.pdf$/i.test(selectedFile.name);
    if (!isPdf) {
      setCreateError("Le fichier doit être un PDF.");
      return;
    }

    setCreateBusy(true);
    setCreateError("");
    setCreateSteps({ create: "running", upload: "idle", complete: "idle" });
    try {
      const created = await client.createDocument({
        filename: createFilename || selectedFile.name,
        content_type: "application/pdf",
        size_bytes: selectedFile.size,
      });
      const id = getDocumentId(created);
      setCreateSteps({ create: "success", upload: "running", complete: "idle" });
      await client.uploadDocument(id, selectedFile, createFilename || selectedFile.name);
      setCreateSteps({ create: "success", upload: "success", complete: "running" });
      await client.completeUpload(id);
      setCreateSteps({ create: "success", upload: "success", complete: "success" });
      setCreateBusy(false);
      setCreateOpen(false);
      void loadDocuments();
      openDetail(id);
    } catch (error) {
      setCreateBusy(false);
      const message = error instanceof ApiError ? `Erreur ${error.status}. ${error.message.slice(0, 160)}` : networkError(baseUrl);
      setCreateError(message);
      setCreateSteps((current) => ({
        create: current.create === "running" ? "failed" : current.create,
        upload: current.upload === "running" ? "failed" : current.upload,
        complete: current.complete === "running" ? "failed" : current.complete,
      }));
    }
  }

  const docRows = useMemo(() => {
    const mapped = documents.map((document) => {
      const status = getDocumentStatus(document);
      const meta = statusMeta(status);
      const id = getDocumentId(document);
      return {
        id,
        filename: getFilename(document),
        statusKey: status,
        statusLabel: meta.label,
        statusColor: meta.color,
        statusBg: meta.bg,
        owner: shortId(document.owner_user_id),
        created: formatDate(document.created_at),
        externalJob: document.external_job_id || "—",
        error: document.current_error_message || "",
      };
    });
    return mapped;
  }, [documents]);

  const activeLabel = activeDef.label;
  const activeTint = activeDef.tint;

  if (view === "login") {
    return (
      <LoginScreen
        baseUrl={baseUrl}
        links={links}
        loginAccount={loginAccount}
        loginBusy={loginBusy}
        loginEmail={loginEmail}
        loginError={loginError}
        loginPassword={loginPassword}
        onBaseUrl={setBaseUrl}
        onLogin={() => void loginWith(loginAccount, loginEmail, loginPassword)}
        onLoginEmail={setLoginEmail}
        onLoginPassword={setLoginPassword}
        onPickAccount={pickLoginAccount}
      />
    );
  }

  return (
    <div className="app-shell">
      <Sidebar
        activeAccount={activeAccount}
        activeEmail={activeSession?.email || ""}
        activeLabel={activeLabel}
        activeOrgShort={shortId(activeSession?.orgId)}
        activeTint={activeTint}
        isDocuments={view === "documents" || view === "detail"}
        links={links}
        onLogout={logout}
        onNavDocuments={navDocuments}
      />
      <main className="main">
        <Header
          activeAccount={activeAccount}
          activeLabel={activeLabel}
          activeTint={activeTint}
          baseHostLabel={baseHost(baseUrl)}
          orgMenuOpen={orgMenuOpen}
          onSwitchAccount={switchAccount}
          onToggleGuide={() => setShowGuide((current) => !current)}
          onToggleOrgMenu={() => setOrgMenuOpen((current) => !current)}
        />
        <div className="content">
          {view === "documents" && (
            <DocumentsView
              activeLabel={activeLabel}
              docsEmpty={!docsLoading && !docsError && docRows.length === 0}
              docsError={docsError}
              docsLoading={docsLoading}
              hasNextPage={nextDocumentsCursor !== null}
              rows={docRows}
              statusFilter={statusFilter}
              onFilter={changeStatusFilter}
              onLoadMore={() => void loadDocuments(nextDocumentsCursor)}
              onOpenCreate={openCreate}
              onOpenDetail={openDetail}
              onReload={() => void loadDocuments()}
            />
          )}
          {view === "detail" && (
            <DetailView
              detail={detail}
              detailError={detailError}
              detailLoading={detailLoading}
              docStatus={docStatus}
              events={events}
              result={result}
              selectedId={selectedId}
              stepStatus={stepStatus}
              streamMode={streamMode}
              onCopy={(value) => void navigator.clipboard?.writeText(value)}
              onNavDocuments={navDocuments}
              onReload={() => void loadDetail(selectedId, false)}
            />
          )}
        </div>
      </main>
      {showGuide && <GuideDrawer onClose={() => setShowGuide(false)} />}
      {createOpen && (
        <CreateDocumentModal
          createBusy={createBusy}
          createError={createError}
          createFilename={createFilename}
          createSteps={createSteps}
          selectedFile={selectedFile}
          onClose={() => !createBusy && setCreateOpen(false)}
          onFilename={setCreateFilename}
          onFilePick={onFilePick}
          onRun={() => void runCreate()}
        />
      )}
    </div>
  );
}

function networkError(baseUrl: string) {
  return `Impossible de joindre l'API (${normalizeBaseUrl(baseUrl)}). Vérifiez que le backend tourne.`;
}

function LoginScreen(props: {
  baseUrl: string;
  links: ReturnType<typeof resolveLinks>;
  loginAccount: AccountKey;
  loginBusy: boolean;
  loginEmail: string;
  loginError: string;
  loginPassword: string;
  onBaseUrl: (value: string) => void;
  onLogin: () => void;
  onLoginEmail: (value: string) => void;
  onLoginPassword: (value: string) => void;
  onPickAccount: (account: AccountKey) => void;
}) {
  return (
    <div className="login-page">
      <section className="login-card">
        <div className="login-brand">
          <div className="brand-row">
            <img className="brand-logo brand-logo-invert" src={LOGO_URL} alt="Primmo" />
            <span className="brand-separator" />
            <span className="eyebrow">Console de démo</span>
          </div>
          <h2>Pipeline de traitement documentaire</h2>
          <p>
            Connectez-vous, déposez un PDF et suivez en temps réel l'OCR, l'extraction, le chunking, l'appel partenaire
            et le webhook.
          </p>
          <div className="demo-account-list">
            <div className="eyebrow">Comptes de démo</div>
            {(Object.keys(ACCOUNTS) as AccountKey[]).map((key) => {
              const account = ACCOUNTS[key];
              const active = props.loginAccount === key;
              return (
                <button
                  className={`demo-account ${active ? "active" : ""}`}
                  key={key}
                  onClick={() => props.onPickAccount(key)}
                  type="button"
                >
                  <span className="avatar square" style={{ background: account.tint }}>
                    {account.initials}
                  </span>
                  <span>
                    <strong>{account.label}</strong>
                    <small>{account.email}</small>
                  </span>
                  <i className="ph ph-arrow-right" />
                </button>
              );
            })}
          </div>
          <div className="demo-password">
            Mot de passe démo : <strong>primmo-demo</strong>
          </div>
        </div>

        <div className="login-form">
          <h1>Connexion</h1>
          <p>Utilisateur d'organisation</p>
          <div className="segmented">
            {(Object.keys(ACCOUNTS) as AccountKey[]).map((key) => (
              <button
                className={props.loginAccount === key ? "active" : ""}
                key={key}
                onClick={() => props.onPickAccount(key)}
                type="button"
              >
                {ACCOUNTS[key].short}
              </button>
            ))}
          </div>
          <TextField label="Email" value={props.loginEmail} onChange={props.onLoginEmail} />
          <TextField label="Mot de passe" type="password" value={props.loginPassword} onChange={props.onLoginPassword} />
          <TextField
            icon="ph-globe-simple"
            label="URL de l'API"
            mono
            value={props.baseUrl}
            onChange={props.onBaseUrl}
          />
          {props.loginError && <Alert message={props.loginError} />}
          <button className="primary wide" disabled={props.loginBusy} onClick={props.onLogin} type="button">
            {props.loginBusy && <i className="ph ph-circle-notch spin" />}
            {props.loginBusy ? "Connexion…" : "Se connecter"}
          </button>
          <div className="link-row">
            <a href={props.links.swagger} target="_blank" rel="noreferrer">
              <i className="ph ph-file-text" />
              Swagger
            </a>
            <a href={props.links.openapi} target="_blank" rel="noreferrer">
              <i className="ph ph-brackets-curly" />
              OpenAPI
            </a>
          </div>
        </div>
      </section>
    </div>
  );
}

function Sidebar(props: {
  activeAccount: AccountKey | null;
  activeEmail: string;
  activeLabel: string;
  activeOrgShort: string;
  activeTint: string;
  isDocuments: boolean;
  links: ReturnType<typeof resolveLinks>;
  onLogout: () => void;
  onNavDocuments: () => void;
}) {
  const initials = props.activeAccount ? ACCOUNTS[props.activeAccount].initials : "A";
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <img className="brand-logo" src={LOGO_URL} alt="Primmo" />
        <span className="eyebrow">Console de démo</span>
      </div>
      <NavSection label="Client">
        <button className={`nav-item ${props.isDocuments ? "active" : ""}`} onClick={props.onNavDocuments} type="button">
          <i className="ph ph-files" />
          Documents
        </button>
      </NavSection>
      <div className="sidebar-spacer" />
      <NavSection label="Liens">
        <SidebarLink href={props.links.swagger} icon="ph-file-text" label="Swagger" />
        <SidebarLink href={props.links.openapi} icon="ph-brackets-curly" label="OpenAPI" />
        <SidebarLink href={props.links.flask} icon="ph-database" label="Flask admin" />
        <SidebarLink href={props.links.minio} icon="ph-hard-drives" label="MinIO" />
      </NavSection>
      <div className="sidebar-user">
        <span className="avatar round" style={{ background: props.activeTint }}>
          {initials}
        </span>
        <span className="user-copy">
          <strong>{props.activeEmail}</strong>
          <small>org {props.activeOrgShort}</small>
        </span>
        <button aria-label="Déconnexion" className="icon-button" onClick={props.onLogout} type="button">
          <i className="ph ph-sign-out" />
        </button>
      </div>
    </aside>
  );
}

function Header(props: {
  activeAccount: AccountKey | null;
  activeLabel: string;
  activeTint: string;
  baseHostLabel: string;
  orgMenuOpen: boolean;
  onSwitchAccount: (account: AccountKey) => void;
  onToggleGuide: () => void;
  onToggleOrgMenu: () => void;
}) {
  const initials = props.activeAccount ? ACCOUNTS[props.activeAccount].initials : "A";
  return (
    <header className="topbar">
      <div className="org-switch">
        <button className="org-button" onClick={props.onToggleOrgMenu} type="button">
          <span className="avatar square small" style={{ background: props.activeTint }}>
            {initials}
          </span>
          <span>{props.activeLabel}</span>
          <i className="ph ph-caret-up-down" />
        </button>
        {props.orgMenuOpen && (
          <div className="org-menu">
            <div className="eyebrow">Changer d'organisation</div>
            {(Object.keys(ACCOUNTS) as AccountKey[]).map((key) => {
              const account = ACCOUNTS[key];
              const active = props.activeAccount === key;
              return (
                <button className={active ? "active" : ""} key={key} onClick={() => props.onSwitchAccount(key)} type="button">
                  <span className="avatar square small" style={{ background: account.tint }}>
                    {account.initials}
                  </span>
                  <span>
                    <strong>{account.label}</strong>
                    <small>{account.email}</small>
                  </span>
                  {active && <i className="ph ph-check" />}
                </button>
              );
            })}
          </div>
        )}
      </div>
      <div className="topbar-spacer" />
      <div className="api-pill" aria-label="API base">
        <span />
        <code>{props.baseHostLabel}</code>
      </div>
      <button className="secondary" onClick={props.onToggleGuide} type="button">
        <i className="ph ph-path" />
        Guide démo
      </button>
    </header>
  );
}

function DocumentsView(props: {
  activeLabel: string;
  docsEmpty: boolean;
  docsError: string;
  docsLoading: boolean;
  hasNextPage: boolean;
  rows: Array<{
    id: string;
    filename: string;
    statusKey: DocumentStatus;
    statusLabel: string;
    statusColor: string;
    statusBg: string;
    owner: string;
    created: string;
    externalJob: string;
    error: string;
  }>;
  statusFilter: string;
  onFilter: (status: string) => void;
  onLoadMore: () => void;
  onOpenCreate: () => void;
  onOpenDetail: (id: string) => void;
  onReload: () => void;
}) {
  const isInitialLoading = props.docsLoading && props.rows.length === 0;
  const filters = [
    ["all", "Tous"],
    ["processing", "Traitement"],
    ["waiting_partner", "Attente partenaire"],
    ["ready", "Prêt"],
    ["failed", "Échec"],
  ] as const;

  return (
    <>
      <PageTitle breadcrumb={["Client", "Documents"]} title="Documents">
        <button className="secondary" onClick={props.onReload} type="button">
          <i className="ph ph-arrow-clockwise" />
          Actualiser
        </button>
        <button className="primary" onClick={props.onOpenCreate} type="button">
          <i className="ph ph-plus" />
          Nouveau document
        </button>
      </PageTitle>
      <div className="toolbar">
        <span className="tenant-pill">
          <i className="ph ph-buildings" />
          {props.activeLabel} — vue isolée par organisation
        </span>
        <span className="toolbar-spacer" />
        {filters.map(([id, label]) => (
          <button className={props.statusFilter === id ? "filter active" : "filter"} key={id} onClick={() => props.onFilter(id)} type="button">
            {label}
          </button>
        ))}
      </div>
      <section className="surface table-surface">
        <div className="doc-table header-row">
          <span>Nom</span>
          <span>Statut</span>
          <span>Propriétaire</span>
          <span>Créé le</span>
          <span>Job externe</span>
          <span />
        </div>
        {isInitialLoading && <LoadingBlock label="Chargement…" />}
        {props.docsError && <InlineError message={props.docsError} />}
        {props.docsEmpty && (
          <div className="empty-state">
            <img src="/assets/status_empty.svg" alt="" />
            <strong>Aucun document</strong>
            <span>Créez une fiche et déposez un PDF pour lancer le pipeline.</span>
            <button className="primary" onClick={props.onOpenCreate} type="button">
              <i className="ph ph-plus" />
              Nouveau document
            </button>
          </div>
        )}
        {!props.docsError &&
          props.rows.map((row) => (
            <button className="doc-table doc-row" key={row.id} onClick={() => props.onOpenDetail(row.id)} type="button">
              <span className="filename-cell">
                <span>
                  <i className="ph ph-file-pdf" />
                  <strong>{row.filename}</strong>
                </span>
                {row.error && <small>{row.error}</small>}
              </span>
              <span>
                <StatusBadge bg={row.statusBg} color={row.statusColor} label={row.statusLabel} />
              </span>
              <span className="muted truncate">{row.owner}</span>
              <span className="muted">{row.created}</span>
              <span className="mono muted truncate">{row.externalJob}</span>
              <span className="open-chip">
                Ouvrir
                <i className="ph ph-arrow-right" />
              </span>
            </button>
          ))}
        {!props.docsError && props.hasNextPage && props.rows.length > 0 && (
          <div className="load-more-row">
            <button className="secondary" disabled={props.docsLoading} onClick={props.onLoadMore} type="button">
              <i className="ph ph-arrow-down" />
              {props.docsLoading ? "Chargement…" : "Charger plus"}
            </button>
          </div>
        )}
      </section>
    </>
  );
}

function DetailView(props: {
  detail: ApiDocument | null;
  detailError: string;
  detailLoading: boolean;
  docStatus: DocumentStatus;
  events: UiEvent[];
  result: ApiResult | null;
  selectedId: string;
  stepStatus: StepStatusMap;
  streamMode: "idle" | "connecting" | "sse" | "polling";
  onCopy: (value: string) => void;
  onNavDocuments: () => void;
  onReload: () => void;
}) {
  const status = props.docStatus || getDocumentStatus(props.detail);
  const meta = statusMeta(status);
  const filename = getFilename(props.detail);
  const externalJob = props.detail?.external_job_id || "—";
  const showResult = status === "ready" && !!props.result;
  const errorMessage = props.detail?.current_error_message || "";
  const eventRows = [...props.events].reverse();
  const stream = streamDescriptor(props.streamMode);

  return (
    <>
      <div className="breadcrumb single">
        <button onClick={props.onNavDocuments} type="button">
          Documents
        </button>
        <i className="ph ph-caret-right" />
        <span>Détail</span>
      </div>
      <div className="detail-heading">
        <div>
          <h1>
            <i className="ph ph-file-pdf" />
            <span>{filename}</span>
          </h1>
          <StatusBadge bg={meta.bg} color={meta.color} label={meta.label} />
        </div>
        <div className="button-row">
          <button className="secondary" onClick={props.onReload} type="button">
            <i className="ph ph-arrow-clockwise" />
            Actualiser
          </button>
        </div>
      </div>
      {props.detailLoading && <LoadingBlock label="Chargement du détail…" />}
      {props.detailError && <InlineError message={props.detailError} />}
      {!props.detailLoading && !props.detailError && (
        <div className="detail-grid">
          <div className="detail-main">
            <section className="surface padded">
              <div className="meta-grid">
                <MetaItem label="Organisation" value={shortId(props.detail?.org_id)} />
                <MetaItem label="Propriétaire" value={shortId(props.detail?.owner_user_id)} />
                <MetaItem label="Créé le" value={formatDate(props.detail?.created_at)} />
                <MetaItem copy label="Document ID" value={props.selectedId || getDocumentId(props.detail)} onCopy={props.onCopy} />
                <MetaItem copy className="wide" label="Job externe" value={externalJob} onCopy={props.onCopy} />
              </div>
            </section>
            <section className="surface padded">
              <div className="section-head">
                <h2>Pipeline</h2>
                <span className="stream-label" style={{ color: stream.color }}>
                  <span className={stream.animate ? "pulse-dot" : ""} style={{ background: stream.color }} />
                  {stream.label}
                </span>
              </div>
              <div className="pipeline">
                {STEP_DEFS.map((step, index) => {
                  const state = props.stepStatus[step.key];
                  const stateMeta = stepStatusMeta(state);
                  const done = state === "success";
                  const running = state === "running" || state === "retrying";
                  const failed = state === "failed";
                  return (
                    <div className="pipeline-step" key={step.key}>
                      {index > 0 && <span className={`connector ${done ? "done" : failed ? "failed" : ""}`} />}
                      <span className={`step-dot ${done ? "done" : running ? "running" : failed ? "failed" : ""}`}>
                        <i className={`${stepIconClass(state, step.icon)} ${running ? "spin" : ""}`} />
                      </span>
                      <strong>{step.label}</strong>
                      <StatusBadge bg={stateMeta.bg} color={stateMeta.color} label={stateMeta.label} small />
                    </div>
                  );
                })}
              </div>
            </section>
            {errorMessage && status !== "ready" && (
              <section className="error-panel">
                <h2>
                  <i className="ph ph-x-circle" />
                  Erreur courante
                </h2>
                <small>{props.detail?.current_error_type || "Erreur"}</small>
                <p>{errorMessage}</p>
              </section>
            )}
            {showResult && props.result && <ResultPanel result={props.result} />}
          </div>
          <aside className="surface events-panel">
            <div className="events-head">
              <strong>Événements</strong>
              <span>flux en direct</span>
            </div>
            {eventRows[0] && (
              <div className="last-event">
                <small>Dernier événement</small>
                <strong>{eventTitle(eventRows[0])}</strong>
                <span>{formatTime(eventRows[0].t)}</span>
              </div>
            )}
            <div className="event-list">
              {!eventRows.length && <div className="empty-events">En attente d'événements…</div>}
              {eventRows.map((event, index) => {
                const stepMeta = stepStatusMeta(event.stepStatus);
                const docMeta = statusMeta(event.docStatus);
                return (
                  <div className="event-row" key={`${event.t}-${index}`}>
                    <span style={{ background: stepMeta.color }} />
                    <div>
                      <div>
                        <strong>{eventTitle(event)}</strong>
                        <code>{formatTime(event.t)}</code>
                      </div>
                      <p>
                        <StatusBadge bg={stepMeta.bg} color={stepMeta.color} label={stepMeta.label} small />
                        <small>doc · {docMeta.label}</small>
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          </aside>
        </div>
      )}
    </>
  );
}

function CreateDocumentModal(props: {
  createBusy: boolean;
  createError: string;
  createFilename: string;
  createSteps: CreateStepState;
  selectedFile: File | null;
  onClose: () => void;
  onFilename: (value: string) => void;
  onFilePick: (files: FileList | null) => void;
  onRun: () => void;
}) {
  const hasFile = !!props.selectedFile;
  return (
    <div className="modal-backdrop" onClick={props.onClose}>
      <section className="modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <h2>Nouveau document</h2>
          <button className="icon-button" onClick={props.onClose} type="button">
            <i className="ph ph-x" />
          </button>
        </div>
        <div className="modal-body">
          <label className={`dropzone ${hasFile ? "has-file" : ""}`} htmlFor="pm-file">
            <i className="ph ph-cloud-arrow-up" />
            {hasFile ? (
              <strong>
                {props.selectedFile?.name}
                <span> · {formatSize(props.selectedFile?.size)}</span>
              </strong>
            ) : (
              <strong>Déposez un PDF</strong>
            )}
            <small>application/pdf</small>
          </label>
          <input id="pm-file" type="file" accept="application/pdf,.pdf" hidden onChange={(event) => props.onFilePick(event.target.files)} />
          {hasFile && <TextField label="Nom du fichier" value={props.createFilename} onChange={props.onFilename} />}
          <div className="create-steps">
            <CreateStep label="Création de la fiche" state={props.createSteps.create} />
            <CreateStep label="Upload du fichier PDF" state={props.createSteps.upload} />
            <CreateStep label="Confirmation de l'upload" state={props.createSteps.complete} />
          </div>
          {props.createError && <Alert message={props.createError} />}
          <div className="modal-actions">
            <button className="secondary" onClick={props.onClose} type="button">
              Annuler
            </button>
            <button className="primary" disabled={props.createBusy} onClick={props.onRun} type="button">
              {props.createBusy && <i className="ph ph-circle-notch spin" />}
              Créer et uploader
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

function ResultPanel({ result }: { result: ApiResult }) {
  const metadata = result.metadata_json || {};
  const partner = result.partner_result_json || {};
  const chunks = result.chunks_json || [];
  return (
    <section className="surface padded result-panel">
      <h2>
        <i className="ph ph-check-circle" />
        Résultat extrait
      </h2>
      <TextBlock label="Texte OCR" value={result.ocr_text || ""} />
      <JsonBlock label="Métadonnées" value={JSON.stringify(metadata, null, 2)} />
      <div className="card-label">
        Chunks <span>· {chunks.length}</span>
      </div>
      <div className="chunks">
        {chunks.map((chunk, index) => (
          <div key={`${chunk}-${index}`}>
            <span>{index + 1}</span>
            <p>{chunk}</p>
          </div>
        ))}
      </div>
      <JsonBlock label="Résultat partenaire" value={JSON.stringify(partner, null, 2)} />
    </section>
  );
}

function GuideDrawer({ onClose }: { onClose: () => void }) {
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="guide-drawer">
        <div className="drawer-head">
          <h2>
            <i className="ph ph-path" />
            Parcours de démo
          </h2>
          <button className="icon-button" onClick={onClose} type="button">
            <i className="ph ph-x" />
          </button>
        </div>
        <div className="guide-list">
          {GUIDE_STEPS.map((step, index) => (
            <div key={step}>
              <span>{index + 1}</span>
              <p>{step}</p>
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}

function PageTitle({ breadcrumb, children, title }: { breadcrumb: string[]; children?: React.ReactNode; title: string }) {
  return (
    <div className="page-title">
      <div>
        <div className="breadcrumb">
          {breadcrumb.map((part, index) => (
            <span key={part}>
              {index > 0 && <i className="ph ph-caret-right" />}
              <span className={index === breadcrumb.length - 1 ? "current" : ""}>{part}</span>
            </span>
          ))}
        </div>
        <h1>{title}</h1>
      </div>
      <div className="title-actions">{children}</div>
    </div>
  );
}

function NavSection({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <div className="nav-section">
      <div className="nav-label">{label}</div>
      {children}
    </div>
  );
}

function SidebarLink({ href, icon, label }: { href: string; icon: string; label: string }) {
  return (
    <a className="sidebar-link" href={href} target="_blank" rel="noreferrer">
      <i className={`ph ${icon}`} />
      {label}
      <i className="ph ph-arrow-square-out" />
    </a>
  );
}

function TextField(props: {
  icon?: string;
  label: string;
  mono?: boolean;
  type?: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="field">
      <span>{props.label}</span>
      <span className={props.icon ? "input-wrap" : ""}>
        {props.icon && <i className={`ph ${props.icon}`} />}
        <input
          className={`input ${props.mono ? "mono" : ""}`}
          type={props.type || "text"}
          value={props.value}
          onChange={(event) => props.onChange(event.target.value)}
        />
      </span>
    </label>
  );
}

function StatusBadge({ bg, color, label, small = false }: { bg: string; color: string; label: string; small?: boolean }) {
  return (
    <span className={`status-badge ${small ? "small" : ""}`} style={{ background: bg, color }}>
      <span style={{ background: color }} />
      {label}
    </span>
  );
}

function Alert({ message }: { message: string }) {
  return (
    <div className="alert">
      <i className="ph ph-warning-circle" />
      <span>{message}</span>
    </div>
  );
}

function InlineError({ message }: { message: string }) {
  return (
    <div className="inline-error">
      <i className="ph ph-warning-circle" />
      <span>{message}</span>
    </div>
  );
}

function LoadingBlock({ label }: { label: string }) {
  return (
    <div className="loading-block">
      <i className="ph ph-circle-notch spin" />
      <span>{label}</span>
    </div>
  );
}

function MetaItem(props: { className?: string; copy?: boolean; label: string; value: string; onCopy?: (value: string) => void }) {
  return (
    <div className={props.className}>
      <span className="card-label">{props.label}</span>
      <button className={props.copy ? "meta-value copy" : "meta-value"} onClick={() => props.copy && props.onCopy?.(props.value)} type="button">
        {props.value}
      </button>
    </div>
  );
}

function TextBlock({ label, value }: { label: string; value: string }) {
  return (
    <>
      <div className="card-label">{label}</div>
      <div className="text-block">{value || "—"}</div>
    </>
  );
}

function JsonBlock({ label, value }: { label: string; value: string }) {
  return (
    <>
      <div className="card-label">{label}</div>
      <pre className="json-block">{value || "{}"}</pre>
    </>
  );
}

function CodeBox({ label, value }: { label: string; value: string }) {
  return (
    <>
      <div className="card-label">{label}</div>
      <div className="code-box">{value}</div>
    </>
  );
}

function CreateStep({ label, state }: { label: string; state: CreateStepStatus }) {
  const icon = state === "running" ? "ph-circle-notch" : state === "success" ? "ph-check-circle" : state === "failed" ? "ph-x-circle" : "ph-circle";
  return (
    <div className={`create-step ${state}`}>
      <span>
        <i className={`ph ${icon} ${state === "running" ? "spin" : ""}`} />
      </span>
      <strong>{label}</strong>
    </div>
  );
}

function streamDescriptor(mode: "idle" | "connecting" | "sse" | "polling") {
  if (mode === "sse") return { label: "Flux SSE", color: "#16A34A", animate: true };
  if (mode === "polling") return { label: "Polling", color: "#C73A02", animate: false };
  if (mode === "connecting") return { label: "Connexion…", color: "#3D5AFE", animate: true };
  return { label: "Arrêté", color: "#9CA3AF", animate: false };
}

function eventTitle(event: UiEvent) {
  return STEP_DEFS.find((step) => step.key === event.step)?.label || event.step || event.type || "event";
}

export default App;
