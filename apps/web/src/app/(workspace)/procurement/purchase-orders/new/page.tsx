"use client";

import { useRouter } from "next/navigation";
import { DocEditor } from "@/components/documents";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { PO_HEADER } from "@/features/fields";
import { api } from "@/lib/api";
import { today } from "@/lib/format";

export default function NewPO() {
  const router = useRouter();
  const toast = useToast();
  return (
    <>
      <PageHeader title="New purchase order" crumbs={[{ label: "Operations" }, { label: "Purchase orders", href: "/procurement/purchase-orders" }, { label: "New" }]} />
      <DocEditor title="PO details" headerFields={PO_HEADER} initialHeader={{ order_date: today() }} priceField="purchase_price" submitLabel="Save draft"
        onSubmit={async (h, lines) => {
          const po = await api.post<{ id: string }>("/procurement/purchase-orders", { ...h, lines }, { idempotent: true });
          toast.success("Purchase order saved");
          router.push(`/procurement/purchase-orders/${po.id}`);
        }} />
    </>
  );
}
