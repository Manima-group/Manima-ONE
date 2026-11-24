"use client";

import { ChevronRight, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { DataTable, type Column, type Filter } from "./data-table";
import { FormDialog, type FieldDef } from "./form";
import { useToast } from "./toast";
import { Alert, Button, Dialog } from "./ui";

export function PageHeader({ title, crumbs = [], actions, subtitle }: {
  title: React.ReactNode; crumbs?: { label: string; href?: string }[]; actions?: React.ReactNode; subtitle?: React.ReactNode;
}) {
  return (
    <div className="mb-5 space-y-1.5">
      {crumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1 text-xs text-muted">
          {crumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-1">
              {c.href ? <Link href={c.href} className="hover:text-brand">{c.label}</Link> : <span>{c.label}</span>}
              {i < crumbs.length - 1 && <ChevronRight className="h-3 w-3" />}
            </span>
          ))}
        </nav>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">{title}</h1>
          {subtitle && <p className="text-sm text-muted">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
    </div>
  );
}

export function ConfirmButton({ label, confirm, onConfirm, variant = "secondary", size = "sm", icon, disabled, title = "Are you sure?" }: {
  label: React.ReactNode; confirm: string; onConfirm: () => Promise<unknown>; variant?: "secondary" | "danger" | "primary" | "ghost";
  size?: "sm" | "md"; icon?: React.ReactNode; disabled?: boolean; title?: string;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  return (
    <>
      <Button variant={variant} size={size} onClick={() => setOpen(true)} disabled={disabled}>{icon}{label}</Button>
      <Dialog open={open} onClose={() => setOpen(false)} title={title}
        footer={<>
          <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant={variant === "danger" ? "danger" : "primary"} loading={busy} onClick={async () => {
            setBusy(true);
            try { await onConfirm(); setOpen(false); } catch (e) { toast.error(e); } finally { setBusy(false); }
          }}>Confirm</Button>
        </>}>
        <p className="text-sm text-muted">{confirm}</p>
      </Dialog>
    </>
  );
}

export function ModuleBanner({ module }: { module: string }) {
  const { me, writable } = useSession();
  const cap = me?.capabilities?.modules[module];
  if (!cap || writable(module)) return null;
  const msg: Record<string, string> = {
    MODULE_READ_ONLY: "This module is read-only. You can view and export history, but not make changes.",
    MODULE_DISABLED: "This module is switched off. Existing records remain readable.",
    MODULE_DRAINING: "This module is being switched off.",
    NOT_IN_PLAN: "This module is not in your plan. Existing records remain readable.",
    FEATURE_DISABLED_PLATFORM: "This module is temporarily unavailable.",
    FEATURE_REVOKED: "Access to this module has been revoked for your company.",
  };
  return <div className="mb-4"><Alert>{msg[cap.reason ?? ""] ?? "This module is read-only right now."}</Alert></div>;
}

type Row = Record<string, unknown> & { id: string };

/** Generic list + create/edit/delete page for simple resources. */
export function ResourcePage<T extends Row>({
  title, crumbs, endpoint, columns, fields, filters, createPerm, updatePerm, deletePerm, module, rowHref, defaults = {},
  toEdit, nounSingular, extraActions, subtitle,
}: {
  title: string; crumbs?: { label: string; href?: string }[]; endpoint: string; columns: Column<T>[]; fields: FieldDef[];
  filters?: Filter[]; createPerm?: string; updatePerm?: string; deletePerm?: string; module?: string;
  rowHref?: (r: T) => string; defaults?: Record<string, unknown>; toEdit?: (r: T) => Record<string, unknown>;
  nounSingular: string; extraActions?: (r: T, reload: () => void) => React.ReactNode; subtitle?: string;
}) {
  const { can, writable } = useSession();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<T | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const canWrite = !module || writable(module);
  const reload = () => setReloadKey((k) => k + 1);

  return (
    <>
      <PageHeader title={title} crumbs={crumbs} subtitle={subtitle}
        actions={createPerm && can(createPerm) && canWrite && (
          <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> New {nounSingular}</Button>
        )} />
      {module && <ModuleBanner module={module} />}
      <DataTable<T> endpoint={endpoint} columns={columns} filters={filters} rowHref={rowHref} reloadKey={reloadKey}
        actions={(r, rl) => (
          <div className="flex justify-end gap-1">
            {extraActions?.(r, rl)}
            {updatePerm && can(updatePerm) && canWrite && (
              <Button variant="ghost" size="sm" onClick={() => setEditing(r)} aria-label={`Edit ${nounSingular}`}><Pencil className="h-4 w-4" /></Button>
            )}
            {deletePerm && can(deletePerm) && canWrite && (
              <ConfirmButton variant="ghost" label="" icon={<Trash2 className="h-4 w-4 text-red-600" />}
                confirm={`Delete this ${nounSingular}? It will be removed from lists (history is kept).`}
                onConfirm={async () => { await api.del(`${endpoint}/${r.id}`); toast.success(`${nounSingular} deleted`); rl(); }} />
            )}
          </div>
        )} />
      <FormDialog open={creating} onClose={() => setCreating(false)} title={`New ${nounSingular}`} fields={fields} initial={defaults}
        submit={async (v) => { await api.post(endpoint, v); toast.success(`${nounSingular} created`); reload(); }} />
      <FormDialog open={!!editing} onClose={() => setEditing(null)} title={`Edit ${nounSingular}`} fields={fields}
        initial={editing ? (toEdit ? toEdit(editing) : editing) : {}}
        submit={async (v) => { await api.patch(`${endpoint}/${editing!.id}`, v); toast.success("Saved"); reload(); }} />
    </>
  );
}
