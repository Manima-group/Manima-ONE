"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { DataTable } from "@/components/data-table";
import { useToast } from "@/components/toast";
import { Alert, Button, Dialog, Field, Input, Select, StatusBadge } from "@/components/ui";
import { api, ApiError, type Page } from "@/lib/api";
import { date, qty } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type T = { id: string; number: string; from_name: string; to_name: string; status: string; transfer_date: string; lines: { name: string; qty: string }[] };

export default function TransfersPanel({ warehouses }: { warehouses: { value: string; label: string }[] }) {
  const { can, writable } = useSession();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState(0);
  const [form, setForm] = useState({ from: "", to: "", lines: [{ item_id: "", qty: "1" }] });
  const [err, setErr] = useState<string | null>(null);
  const items = useQuery<Page<{ id: string; sku: string; name: string }>>(open ? "/catalog/items?type=goods&limit=200" : null);
  const w = writable("inventory") && can("inventory.transfer.manage");
  const act = async (id: string, a: string) => { try { await api.post(`/inventory/transfers/${id}:${a}`); toast.success(`Transfer ${a === "cancel" ? "cancelled" : a + "ed"}`); setKey((k) => k + 1); } catch (e) { toast.error(e); } };
  return (
    <div className="space-y-3">
      {w && <div className="flex justify-end"><Button onClick={() => { setForm({ from: warehouses[0]?.value ?? "", to: warehouses[1]?.value ?? "", lines: [{ item_id: "", qty: "1" }] }); setErr(null); setOpen(true); }}><Plus className="h-4 w-4" />New transfer</Button></div>}
      <DataTable<T> endpoint="/inventory/transfers" reloadKey={key}
        filters={[{ key: "status", label: "Status", options: ["draft", "in_transit", "received", "cancelled"].map((v) => ({ value: v, label: v.replace("_", " ") })) }]}
        columns={[
          { key: "number", header: "Transfer", render: (r) => <span className="font-medium">{r.number}</span> },
          { key: "route", header: "Route", render: (r) => `${r.from_name} → ${r.to_name}` },
          { key: "lines", header: "Items", render: (r) => r.lines.map((l) => `${l.name} × ${qty(l.qty)}`).join(", ") },
          { key: "transfer_date", header: "Date", render: (r) => date(r.transfer_date) },
          { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
        ]}
        actions={(r) => w && (
          <div className="flex justify-end gap-1">
            {r.status === "draft" && <><Button size="sm" onClick={() => act(r.id, "dispatch")}>Dispatch</Button><Button size="sm" variant="ghost" onClick={() => act(r.id, "cancel")}>Cancel</Button></>}
            {r.status === "in_transit" && <Button size="sm" onClick={() => act(r.id, "receive")}>Receive</Button>}
          </div>
        )} />
      <Dialog open={open} onClose={() => setOpen(false)} title="New stock transfer" wide
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={async () => {
            try {
              await api.post("/inventory/transfers", { from_warehouse_id: form.from, to_warehouse_id: form.to, lines: form.lines.filter((l) => l.item_id) }, { idempotent: true });
              toast.success("Transfer created"); setOpen(false); setKey((k) => k + 1);
            } catch (e) { setErr((e as ApiError).message); }
          }}>Create transfer</Button></>}>
        <div className="space-y-4">
          {err && <Alert tone="red">{err}</Alert>}
          <div className="grid grid-cols-2 gap-4">
            <Field label="From"><Select value={form.from} onChange={(e) => setForm({ ...form, from: e.target.value })}>{warehouses.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</Select></Field>
            <Field label="To"><Select value={form.to} onChange={(e) => setForm({ ...form, to: e.target.value })}>{warehouses.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</Select></Field>
          </div>
          {form.lines.map((l, i) => (
            <div key={i} className="flex gap-2">
              <Select value={l.item_id} aria-label="Item" onChange={(e) => setForm({ ...form, lines: form.lines.map((x, j) => (j === i ? { ...x, item_id: e.target.value } : x)) })}>
                <option value="">Select item…</option>
                {(items.data?.data ?? []).map((it) => <option key={it.id} value={it.id}>{it.sku} · {it.name}</option>)}
              </Select>
              <Input className="w-28" type="number" min="0" step="any" aria-label="Quantity" value={l.qty} onChange={(e) => setForm({ ...form, lines: form.lines.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)) })} />
              <Button variant="ghost" size="icon" aria-label="Remove" disabled={form.lines.length === 1} onClick={() => setForm({ ...form, lines: form.lines.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
          <Button variant="secondary" size="sm" onClick={() => setForm({ ...form, lines: [...form.lines, { item_id: "", qty: "1" }] })}><Plus className="h-4 w-4" />Add item</Button>
        </div>
      </Dialog>
    </div>
  );
}
