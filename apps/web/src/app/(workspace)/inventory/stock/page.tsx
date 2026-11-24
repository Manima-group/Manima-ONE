"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { DataTable } from "@/components/data-table";
import { FormDialog } from "@/components/form";
import { ModuleBanner, PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Badge, Button, Tabs } from "@/components/ui";
import { WAREHOUSE_FIELDS } from "@/features/fields";
import { api } from "@/lib/api";
import { dateTime, label, money, qty } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import TransfersPanel from "../transfers/panel";

type Stock = { item_id: string; sku: string; name: string; unit: string; on_hand: string; reserved: string; available: string; reorder_level: string; value: string; low: boolean };
type Ledger = { id: string; item_name: string; warehouse_name: string; qty_change: string; balance_after: string; reason: string; ref_number: string | null; note: string | null; occurred_at: string };
type WH = { id: string; name: string; code: string; is_default: boolean; active: boolean; address: Record<string, string> };

function Inventory() {
  const { can, writable } = useSession();
  const toast = useToast();
  const params = useSearchParams();
  const [tab, setTab] = useState("stock");
  const [adj, setAdj] = useState(false);
  const [whOpen, setWhOpen] = useState<WH | "new" | null>(null);
  const [key, setKey] = useState(0);
  const whs = useQuery<WH[]>("/inventory/warehouses", [key]);
  const w = writable("inventory");
  const whOptions = (whs.data ?? []).map((x) => ({ value: x.id, label: x.name }));
  return (
    <>
      <PageHeader title="Inventory" crumbs={[{ label: "Operations" }, { label: "Inventory" }]}
        actions={w && can("inventory.adjustment.create") && <Button onClick={() => setAdj(true)}>Adjust stock</Button>} />
      <ModuleBanner module="inventory" />
      <div className="mb-4"><Tabs value={tab} onChange={setTab} tabs={[{ key: "stock", label: "Stock levels" }, { key: "ledger", label: "Stock ledger" },
        { key: "transfers", label: "Transfers" }, { key: "warehouses", label: "Warehouses" }]} /></div>
      {tab === "stock" && (
        <DataTable<Stock> endpoint="/inventory/stock" reloadKey={key} searchPlaceholder="Search item or SKU" extraParams={params.get("low") ? { low_only: "true" } : undefined}
          filters={[{ key: "warehouse_id", label: "Warehouse", options: whOptions }, { key: "low_only", label: "Stock", options: [{ value: "true", label: "Low stock only" }] }]}
          columns={[
            { key: "sku", header: "SKU", render: (r) => <span className="font-mono text-xs">{r.sku}</span> },
            { key: "name", header: "Item", render: (r) => <span className="font-medium">{r.name} {r.low && <Badge tone="red">low</Badge>}</span> },
            { key: "on_hand", header: "On hand", align: "right", render: (r) => `${qty(r.on_hand)} ${r.unit}` },
            { key: "reserved", header: "Reserved", align: "right", render: (r) => qty(r.reserved) },
            { key: "available", header: "Available", align: "right", render: (r) => <span className="font-medium">{qty(r.available)}</span> },
            { key: "reorder_level", header: "Reorder at", align: "right", render: (r) => qty(r.reorder_level) },
            { key: "value", header: "Value", align: "right", render: (r) => money(r.value) },
          ]} />
      )}
      {tab === "ledger" && (
        <DataTable<Ledger> endpoint="/inventory/ledger" reloadKey={key} searchPlaceholder="Search reference or note"
          filters={[{ key: "warehouse_id", label: "Warehouse", options: whOptions },
            { key: "reason", label: "Reason", options: ["opening", "receipt", "sale", "transfer_out", "transfer_in", "adjustment", "return"].map((v) => ({ value: v, label: label(v) })) }]}
          columns={[
            { key: "occurred_at", header: "When", render: (r) => dateTime(r.occurred_at) },
            { key: "item_name", header: "Item" }, { key: "warehouse_name", header: "Warehouse" },
            { key: "reason", header: "Reason", render: (r) => label(r.reason) },
            { key: "ref_number", header: "Reference", render: (r) => r.ref_number ?? r.note ?? "—" },
            { key: "qty_change", header: "Change", align: "right", render: (r) => <span className={Number(r.qty_change) < 0 ? "text-red-600" : "text-green-700"}>{Number(r.qty_change) > 0 ? "+" : ""}{qty(r.qty_change)}</span> },
            { key: "balance_after", header: "Balance", align: "right", render: (r) => qty(r.balance_after) },
          ]} />
      )}
      {tab === "transfers" && <TransfersPanel warehouses={whOptions} />}
      {tab === "warehouses" && (
        <div className="space-y-3">
          {w && can("inventory.warehouse.manage") && <div className="flex justify-end"><Button onClick={() => setWhOpen("new")}>New warehouse</Button></div>}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {(whs.data ?? []).map((x) => (
              <div key={x.id} className="rounded-lg border border-line bg-white p-4 shadow-sm">
                <div className="flex items-start justify-between">
                  <div><p className="font-medium">{x.name}</p><p className="font-mono text-xs text-muted">{x.code}</p></div>
                  <div className="flex gap-1">{x.is_default && <Badge tone="orange">default</Badge>}{!x.active && <Badge>inactive</Badge>}</div>
                </div>
                <p className="mt-2 text-sm text-muted">{[x.address?.line1, x.address?.city].filter(Boolean).join(", ") || "No address"}</p>
                {w && can("inventory.warehouse.manage") && <Button size="sm" variant="secondary" className="mt-3" onClick={() => setWhOpen(x)}>Edit</Button>}
              </div>
            ))}
          </div>
        </div>
      )}
      <FormDialog open={adj} onClose={() => setAdj(false)} title="Adjust stock" submitLabel="Post adjustment"
        fields={[
          { name: "item_id", label: "Item", type: "remote", endpoint: "/catalog/items?type=goods&limit=200", required: true, optionLabel: (r) => `${r.sku} · ${r.name}` },
          { name: "warehouse_id", label: "Warehouse", type: "select", required: true, options: whOptions },
          { name: "qty_change", label: "Quantity change", type: "number", required: true, hint: "Positive to add, negative to remove" },
          { name: "reason", label: "Reason", type: "select", required: true, options: ["opening", "count_correction", "damage", "expiry", "theft", "other"].map((v) => ({ value: v, label: label(v) })) },
          { name: "note", label: "Note", colSpan: 2 },
        ]}
        initial={{ warehouse_id: whs.data?.[0]?.id, reason: "count_correction" }}
        submit={async (v) => { await api.post("/inventory/adjustments", v, { idempotent: true }); toast.success("Stock adjusted"); setKey((k) => k + 1); }} />
      <FormDialog open={!!whOpen} onClose={() => setWhOpen(null)} title={whOpen === "new" ? "New warehouse" : "Edit warehouse"} fields={WAREHOUSE_FIELDS}
        initial={whOpen === "new" || !whOpen ? { active: true, address: {} } : whOpen}
        submit={async (v) => {
          if (whOpen === "new") await api.post("/inventory/warehouses", v); else await api.patch(`/inventory/warehouses/${(whOpen as WH).id}`, v);
          toast.success("Warehouse saved"); setKey((k) => k + 1);
        }} />
    </>
  );
}

export default function Page() {
  return <Suspense><Inventory /></Suspense>;
}
