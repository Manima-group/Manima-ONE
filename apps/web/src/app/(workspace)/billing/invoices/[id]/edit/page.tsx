"use client";

import { useParams, useRouter } from "next/navigation";
import { DocEditor, linesFromDoc } from "@/components/documents";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { ErrorState, Loading } from "@/components/ui";
import { INVOICE_HEADER } from "@/features/fields";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/hooks";

type Inv = Record<string, unknown> & { id: string; version: number; lines: Record<string, unknown>[]; sales_order_id: string | null };

export default function EditInvoice() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const { data: inv, error, loading } = useQuery<Inv>(`/billing/invoices/${id}`);
  if (loading && !inv) return <Loading />;
  if (error || !inv) return <ErrorState error={error} />;
  const header = Object.fromEntries(INVOICE_HEADER.map((f) => [f.name, inv[f.name] ?? ""]));
  return (
    <>
      <PageHeader title="Edit draft invoice" crumbs={[{ label: "Billing" }, { label: "Invoices", href: "/billing/invoices" }, { label: "Edit" }]} />
      <DocEditor title="Invoice details" headerFields={INVOICE_HEADER} initialHeader={header} initialLines={linesFromDoc(inv.lines)} submitLabel="Save draft"
        onSubmit={async (h, lines) => {
          await api.patch(`/billing/invoices/${id}`, { ...h, lines, sales_order_id: inv.sales_order_id, version: inv.version });
          toast.success("Invoice saved");
          router.push(`/billing/invoices/${id}`);
        }} />
    </>
  );
}
