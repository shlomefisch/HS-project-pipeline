// Shapes returned by the API. Kept by hand for now; can be generated from /api/openapi.json later.

export type Role = "pending" | "rep" | "back_office" | "management" | "viewer";

export interface User {
  id: number;
  email: string;
  name: string;
  role: Role;
  is_admin: boolean;
  home_showroom: string | null;
  default_class: string | null;
  active: boolean;
  has_password?: boolean;
  must_change_password?: boolean;
  last_login_at?: string | null;
}

export interface Entity {
  id: number;
  kind: "person" | "company";
  name: string;
  company_id: number | null;
  phone: string | null;
  email: string | null;
  address: string | null;
  notes: string | null;
  active: boolean;
  merged_into_id: number | null;
}

export interface Match {
  entity: Entity;
  reasons: string[];
}

export interface JobRole {
  id: number;
  role: string;
  active: boolean;
  started_at: string;
  ended_at: string | null;
  entity: Entity;
}

export interface Area {
  id: number;
  job_id: number;
  name: string;
  status: "open" | "decided" | "dropped" | "on_hold";
  hold_until: string | null;
  hold_reason: string | null;
  sort_order: number;
  footage: number | null;
  footage_source: "customer" | "designer" | "installer" | "takeoff" | null;
  footage_by: string | null;
  footage_confidence: "approximate" | "confirmed" | null;
  footage_set_at: string | null;
}

export interface Tag {
  id: number;
  candidate_id: number;
  area_id: number;
  status: "considering" | "chosen" | "declined";
  quantity: number | null;
  unit: string;
  reason: string | null;
  decided_at: string | null;
  avail_status?: "available" | "two_lots" | "override" | "short" | "confirmed" | null;
  avail_lot?: string | null;
  avail_free?: number | null;
  avail_need?: number | null;
  avail_note?: string | null;
  avail_summary?: string | null;
  avail_checked_at?: string | null;
}

export interface Item {
  netsuite_id: number;
  name: string;
  sku: string | null;
  unit?: string | null;
  size: string | null;
  finish: string | null;
  is_lot?: boolean;
}

export interface SyncRun {
  id: number;
  mode: "full" | "changes";
  started_at: string;
  finished_at: string | null;
  status: "running" | "ok" | "failed";
  rows_seen: number;
  error: string | null;
}

export interface ItemSyncStatus {
  configured: boolean;
  every_minutes: number;
  items_active: number;
  items_total: number;
  items_stock: number;
  items_with_unit: number;
  running: boolean;
  runs: SyncRun[];
}

export interface Candidate {
  id: number;
  source: "stock" | "local" | "overseas";
  netsuite_item_id: number | null;
  name: string | null;
  display_name: string;
  supplier: string | null;
  lead_time_weeks: number | null;
  notes: string | null;
  item: Item | null;
  tags: Tag[];
  needs_lead_time: boolean;
}

export interface Sample {
  id: number;
  description: string;
  status: "requested" | "sent" | "replied" | "cancelled";
  area_id: number | null;
  requested_on: string;
  sent_on: string | null;
  expect_reply_by: string | null;
}

export interface Task {
  id: number;
  job_id: number;
  area_id: number | null;
  title: string;
  notes: string | null;
  assignee_id: number;
  due_date: string;
  status: "open" | "blocked" | "done" | "bad_answer" | "skipped";
  severity: "silent" | "notify" | "interrupt";
  outcome_note: string | null;
  needs_rep_attention: boolean;
  kind?: "takeoff" | null;
  covering_for_id?: number | null;
  job_name?: string;
  job_rep_id?: number;
  overdue?: boolean;
}

export interface Visit {
  id: number;
  job_id: number;
  rep_id: number;
  showroom: string | null;
  kind: "showroom" | "site";
  starts_at: string;
  purpose: string | null;
  expected: string | null;
  status: "scheduled" | "happened" | "no_show" | "cancelled" | "rescheduled";
  job_name?: string;
}

export interface JobSummary {
  id: number;
  name: string;
  address: string | null;
  class_code: string;
  status: "active" | "on_hold" | "lost" | "closed";
  rep: User | null;
  default_contact: Entity | null;
  open_tasks: number;
  open_takeoff_id?: number | null;
  progress?: Progress | null;
  next_due: string | null;
  stuck: boolean;
}

export interface Job extends JobSummary {
  project_type: string | null;
  lead_source: string | null;
  lead_showroom: string | null;
  rep_id: number;
  default_contact_id: number | null;
  hold_until: string | null;
  hold_reason: string | null;
  lost_reason: string | null;
  lost_note: string | null;
  roles: JobRole[];
  areas: Area[];
  candidates: Candidate[];
  samples: Sample[];
  tasks: Task[];
  visits: Visit[];
}

export interface AuditEntry {
  id: number;
  at: string;
  user_id: number | null;
  table_name: string;
  action: "insert" | "update" | "delete";
  changes: Record<string, [unknown, unknown]>;
  story: boolean;
  summary: string | null;
}

export interface Meta {
  classes: string[];
  showrooms: string[];
  role_caps: Record<string, number | null>;
  role_labels: Record<string, string>;
  lead_sources: Record<string, string>;
  project_types: Record<string, string>;
  loss_reasons: Record<string, string>;
  candidate_sources: Record<string, string>;
  event_kinds: Record<string, string>;
  channels: string[];
}

export interface NextStep {
  title: string;
  assignee_id: number;
  due_date: string;
  severity?: "silent" | "notify" | "interrupt";
  notes?: string | null;
  area_id?: number | null;
}

export interface StockRow {
  location: string;
  lot: string | null;
  on_hand: number;
  available: number;
}

export interface Stock {
  item_id: number;
  as_of: string;
  unit: string | null;
  by_lot: boolean;
  rows: StockRow[];
  totals: { on_hand: number; available: number };
}

export interface JobFile {
  id: number;
  job_id: number;
  area_id: number | null;
  kind: "plan" | "photo" | "note" | "other";
  name: string;
  content_type: string | null;
  size_bytes: number | null;
  source: "upload" | "link" | "from_link";
  link_url: string | null;
  link_id: number | null;
  status: "ready" | "fetching" | "needs_download";
  problem: string | null;
  created_at: string;
  created_by: number | null;
  url: string | null;
  opens_inline: boolean;
}

export interface AppSettings {
  takeoff_user_id: number | null;
  takeoff_user: User | null;
}

export interface EstimateLine {
  id: number;
  estimate_id: number;
  tag_id: number | null;
  area_id: number | null;
  netsuite_item_id: number | null;
  description: string;
  quantity: number | null;
  unit: string | null;
  base_price: number | null;
  price: number | null;
  price_note: string | null;
  overridden: boolean;
  amount: number | null;
}

export interface Estimate {
  id: number;
  job_id: number;
  status: "draft" | "pushed" | "discarded";
  note: string | null;
  created_at: string;
  created_by: number | null;
  pushed_at: string | null;
  netsuite_estimate_id: number | null;
  area_ids: number[];
  lines: EstimateLine[];
  total: number;
  warnings: string[];
}

export interface Absence {
  id: number;
  user_id: number;
  cover_id: number;
  starts_on: string;
  ends_on: string;
  note: string | null;
  status: "planned" | "active" | "ended" | "cancelled";
  took_takeoff: boolean;
}

export interface HeldItem {
  id: number;
  label: string;
  job_id?: number;
  job_name?: string | null;
  due_date?: string;
  starts_at?: string;
}

export interface AwayOrGone {
  user: User;
  holds: { jobs: HeldItem[]; tasks: HeldItem[]; visits: HeldItem[]; takeoff: boolean };
  counts: { jobs: number; tasks: number; visits: number; takeoff: number };
  current: Absence | null;
  history: Absence[];
  covering_for: number[];
}

export interface StepTemplate {
  id: number;
  trigger: "job_created" | "takeoff_done" | "estimate_started" | "area_decided";
  playbook: "all" | "single_family" | "projects";
  title: string;
  notes: string | null;
  assignee_kind: "rep" | "takeoff" | "actor" | "user";
  assignee_user_id: number | null;
  due_days: number;
  severity: "silent" | "notify" | "interrupt";
  sort_order: number;
  active: boolean;
}

export interface TemplateList {
  steps: StepTemplate[];
  triggers: Record<string, string>;
  playbooks: Record<string, string>;
  assignee_kinds: Record<string, string>;
}

export interface Progress {
  stages: { key: string; label: string; done: boolean }[];
  done: number;
  current: string;
}
