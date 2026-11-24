"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import { ConfirmButton, PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Alert, Badge, Button, Card, Checkbox, Dialog, ErrorState, Field, Input, Loading } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useQuery } from "@/lib/hooks";

type Role = { id: string; key: string; name: string; description: string | null; is_system: boolean; permissions: string[]; member_count: number };
type Group = { module: string; name: string; permissions: { key: string; description: string }[] };

export default function Roles() {
  const toast = useToast();
  const roles = useQuery<Role[]>("/tenant/roles");
  const cat = useQuery<Group[]>("/tenant/permissions");
  const [edit, setEdit] = useState<{ id?: string; name: string; description: string; permissions: string[]; readOnly?: boolean } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (roles.loading && !roles.data) return <Loading />;
  if (roles.error) return <ErrorState error={roles.error} />;
  const toggle = (k: string, on: boolean) => edit && setEdit({ ...edit, permissions: on ? [...edit.permissions, k] : edit.permissions.filter((x) => x !== k) });
  return (
    <>
      <PageHeader title="Roles & permissions" crumbs={[{ label: "Settings" }, { label: "Roles" }]}
        actions={<Button onClick={() => { setErr(null); setEdit({ name: "", description: "", permissions: [] }); }}><Plus className="h-4 w-4" />Custom role</Button>} />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {roles.data!.map((r) => (
          <Card key={r.id} className="p-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="font-medium">{r.name} {r.is_system ? <Badge>default</Badge> : <Badge tone="orange">custom</Badge>}</p>
                <p className="mt-0.5 text-sm text-muted">{r.description ?? "—"}</p>
              </div>
              <span className="text-xs text-muted">{r.member_count} member{r.member_count === 1 ? "" : "s"}</span>
            </div>
            <p className="mt-2 text-xs text-muted">{r.permissions.length} permissions</p>
            <div className="mt-3 flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => { setErr(null); setEdit({ id: r.id, name: r.name, description: r.description ?? "", permissions: r.permissions, readOnly: r.key === "owner" }); }}>
                {r.key === "owner" ? "View" : "Edit"}
              </Button>
              {!r.is_system && <ConfirmButton label="Delete" variant="ghost" confirm={`Delete role "${r.name}"?`} onConfirm={async () => { await api.del(`/tenant/roles/${r.id}`); toast.success("Role deleted"); roles.reload(); }} />}
            </div>
          </Card>
        ))}
      </div>
      <Dialog open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? `Role: ${edit.name}` : "New custom role"} wide
        footer={!edit?.readOnly && <><Button variant="secondary" onClick={() => setEdit(null)}>Cancel</Button><Button onClick={async () => {
          try {
            setErr(null);
            const body = { name: edit!.name, description: edit!.description || null, permissions: edit!.permissions };
            if (edit!.id) await api.patch(`/tenant/roles/${edit!.id}`, body); else await api.post("/tenant/roles", body);
            toast.success("Role saved"); setEdit(null); roles.reload();
          } catch (e) { setErr((e as ApiError).message); }
        }}>Save role</Button></>}>
        {edit && <fieldset disabled={edit.readOnly} className="space-y-4">
          {err && <Alert tone="red">{err}</Alert>}
          {edit.readOnly && <Alert>The Owner role always has every permission and cannot be edited.</Alert>}
          <div className="grid grid-cols-2 gap-4">
            <Field label="Name" required><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label="Description"><Input value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
          </div>
          {(cat.data ?? []).map((g) => (
            <div key={g.module} className="rounded-md border border-line p-3">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-sm font-semibold">{g.name}</p>
                <button type="button" className="text-xs text-brand" onClick={() => {
                  const keys = g.permissions.map((p) => p.key); const all = keys.every((k) => edit.permissions.includes(k));
                  setEdit({ ...edit, permissions: all ? edit.permissions.filter((k) => !keys.includes(k)) : [...new Set([...edit.permissions, ...keys])] });
                }}>Toggle all</button>
              </div>
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {g.permissions.map((p) => <Checkbox key={p.key} label={<span>{p.description} <span className="text-xs text-muted">({p.key})</span></span>}
                  checked={edit.permissions.includes(p.key)} onChange={(e) => toggle(p.key, e.target.checked)} />)}
              </div>
            </div>
          ))}
        </fieldset>}
      </Dialog>
    </>
  );
}
