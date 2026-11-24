"use client";

import { ResourcePage } from "@/components/page";
import { Badge } from "@/components/ui";
import { ITEM_FIELDS } from "@/features/fields";
import { money } from "@/lib/format";

type Item = { id: string; sku: string; name: string; type: string; hsn_sac: string | null; gst_rate: string; unit: string; price: string; active: boolean; category: string | null };

export default function ItemsPage() {
  return (
    <ResourcePage<Item> title="Products & services" nounSingular="item" crumbs={[{ label: "Sales" }, { label: "Catalog" }]} endpoint="/catalog/items"
      module="catalog" fields={ITEM_FIELDS} createPerm="catalog.item.create" updatePerm="catalog.item.update" deletePerm="catalog.item.delete"
      defaults={{ type: "goods", gst_rate: "18", unit: "nos", price: "0", purchase_price: "0", track_stock: true, active: true, reorder_level: "0" }}
      toEdit={(r) => ({ ...r, gst_rate: String(Number(r.gst_rate)) })}
      filters={[{ key: "type", label: "Type", options: [{ value: "goods", label: "Goods" }, { value: "service", label: "Services" }] },
        { key: "active", label: "Active", options: [{ value: "true", label: "Active" }, { value: "false", label: "Inactive" }] }]}
      columns={[
        { key: "sku", header: "SKU", render: (r) => <span className="font-mono text-xs">{r.sku}</span> },
        { key: "name", header: "Name", render: (r) => <span className="font-medium">{r.name}{!r.active && <Badge className="ml-2">inactive</Badge>}</span> },
        { key: "type", header: "Type", render: (r) => <Badge tone={r.type === "goods" ? "blue" : "purple"}>{r.type}</Badge> },
        { key: "category", header: "Category", render: (r) => r.category ?? "—" },
        { key: "hsn_sac", header: "HSN/SAC", render: (r) => r.hsn_sac ?? "—" },
        { key: "gst_rate", header: "GST", render: (r) => `${Number(r.gst_rate)}%` },
        { key: "price", header: "Price", align: "right", render: (r) => `${money(r.price)} / ${r.unit}` },
      ]} />
  );
}
