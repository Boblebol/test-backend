import type { DemoAccount, ProcessingStepKey, ProcessingStepStatus } from "./types";

export const DEFAULT_API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

export const ACCOUNTS: Record<string, DemoAccount> = {
  alpha: {
    key: "alpha",
    label: "Primmo Alpha",
    short: "Alpha",
    email: "alpha@example.com",
    password: "primmo-demo",
    tint: "#3D5AFE",
    initials: "A",
  },
  beta: {
    key: "beta",
    label: "Primmo Beta",
    short: "Beta",
    email: "beta@example.com",
    password: "primmo-demo",
    tint: "#8A38F5",
    initials: "B",
  },
};

export const DOCUMENT_STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
  waiting_upload: { label: "En attente d'upload", color: "#6B7280", bg: "rgba(97,113,134,.10)" },
  uploaded: { label: "Uploadé", color: "#3D5AFE", bg: "rgba(61,90,254,.10)" },
  processing: { label: "Traitement", color: "#3D5AFE", bg: "rgba(61,90,254,.10)" },
  waiting_partner: { label: "Attente partenaire", color: "#8A38F5", bg: "rgba(138,56,245,.12)" },
  ready: { label: "Prêt", color: "#16A34A", bg: "rgba(22,163,74,.10)" },
  failed: { label: "Échec", color: "#D90048", bg: "rgba(217,0,72,.10)" },
};

export const STEP_DEFS: Array<{ key: ProcessingStepKey; label: string; icon: string }> = [
  { key: "ocr", label: "OCR", icon: "ph-scan" },
  { key: "metadata", label: "Métadonnées", icon: "ph-tag" },
  { key: "chunking", label: "Chunking", icon: "ph-squares-four" },
  { key: "external_call", label: "Appel ext.", icon: "ph-plugs-connected" },
  { key: "partner_webhook", label: "Webhook", icon: "ph-broadcast" },
];

export const STEP_STATUS_META: Record<ProcessingStepStatus, { label: string; color: string; bg: string }> = {
  pending: { label: "En attente", color: "#9CA3AF", bg: "rgba(156,163,175,.10)" },
  running: { label: "En cours", color: "#3D5AFE", bg: "rgba(61,90,254,.10)" },
  retrying: { label: "Nouvel essai", color: "#C73A02", bg: "rgba(199,58,2,.10)" },
  success: { label: "Terminé", color: "#16A34A", bg: "rgba(22,163,74,.10)" },
  waiting_webhook: { label: "Webhook attendu", color: "#8A38F5", bg: "rgba(138,56,245,.12)" },
  failed: { label: "Échec", color: "#D90048", bg: "rgba(217,0,72,.10)" },
  skipped: { label: "Ignoré", color: "#9CA3AF", bg: "rgba(156,163,175,.10)" },
};

export const GUIDE_STEPS = [
  "Connectez-vous avec le compte Alpha (alpha@example.com / primmo-demo).",
  "Cliquez « Nouveau document » et sélectionnez un PDF.",
  "La console crée la fiche, uploade le fichier et confirme l'upload.",
  "Ouverture automatique du détail : pipeline démarre.",
  "Suivez les étapes : OCR → Métadonnées → Chunking → Appel externe.",
  "Si une étape passe « Nouvel essai », montrez le badge retry.",
  "Au statut « Attente partenaire », ouvrez Flask admin (:8001).",
  "Depuis Flask admin, validez ou invalidez le webhook partenaire.",
  "Revenez au détail : statut « Prêt », résultats extraits visibles.",
  "Basculez sur Beta (menu org) : isolation tenant démontrée.",
  "Utilisez Flask admin pour les actions internes et les batches de test.",
  "Gardez Swagger ouvert pour tester les endpoints directement.",
];
