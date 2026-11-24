"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { DocEditor } from "@/components/documents";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { INVOICE_HEADER } from "@/features/fields";
import { api } from "@/lib/api";
import { today } from "@/lib/format";

function NewInvoice() {
  const router = useRouter();
  const toast = useToast();
  const account = useSearchParams().get("account");
  return (
    <>
      <PageHeader title="New invoice" crumbs={[{ label: "Billing" }, { label: "Invoices", href: "/billing/invoices" }, { label: "New" }]} />
      <DocEditor title="Invoice details" headerFields={INVOICE_HEADER} initialHeader={{ account_id: account ?? "", invoice_date: today(), scenario: "" }}
        submitLabel="Save draft" onSubmit={async (h, lines) => {
          const inv = await api.post<{ id: string }>("/billing/invoices", { ...h, lines }, { idempotent: true });
          toast.success("Draft invoice saved");
          router.push(`/billing/invoices/${inv.id}`);
        }} />
    </>
  );
}

export default function Page() {
  return <Suspense><NewInvoice /></Suspense>;
}
