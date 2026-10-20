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
}

export interface Item {
  netsuite_id: number;
  name: string;
  sku: string | null;
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
