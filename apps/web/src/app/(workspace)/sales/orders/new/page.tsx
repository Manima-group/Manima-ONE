"use client";

import { useRouter } from "next/navigation";
import { DocEditor } from "@/components/documents";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { ORDER_HEADER } from "@/features/fields";
import { api } from "@/lib/api";
import { today } from "@/lib/format";

export default function NewOrder() {
  const router = useRouter();
  const toast = useToast();
  return (
    <>
      <PageHeader title="New sales order" crumbs={[{ label: "Sales" }, { label: "Sales orders", href: "/sales/orders" }, { label: "New" }]} />
      <DocEditor title="Order details" headerFields={ORDER_HEADER} initialHeader={{ order_date: today() }} submitLabel="Create order"
        onSubmit={async (h, lines) => {
          const so = await api.post<{ id: string }>("/sales/orders", { ...h, lines }, { idempotent: true });
          toast.success("Sales order created");
          router.push(`/sales/orders/${so.id}`);
        }} />
    </>
  );
}
