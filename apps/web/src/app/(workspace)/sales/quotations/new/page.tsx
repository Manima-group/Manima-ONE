"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { DocEditor } from "@/components/documents";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { QUOTE_HEADER } from "@/features/fields";
import { api } from "@/lib/api";
import { today } from "@/lib/format";

function NewQuote() {
  const router = useRouter();
  const toast = useToast();
  const account = useSearchParams().get("account");
  return (
    <>
      <PageHeader title="New quotation" crumbs={[{ label: "Sales" }, { label: "Quotations", href: "/sales/quotations" }, { label: "New" }]} />
      <DocEditor title="Quotation details" headerFields={QUOTE_HEADER} initialHeader={{ account_id: account ?? "", issue_date: today() }} submitLabel="Save draft"
        onSubmit={async (h, lines) => {
          const q = await api.post<{ id: string; approval_status: string }>("/sales/quotations", { ...h, lines }, { idempotent: true });
          toast.success("Quotation saved", q.approval_status === "pending" ? "Discount needs approval before sending" : undefined);
          router.push(`/sales/quotations/${q.id}`);
        }} />
    </>
  );
}

export default function Page() {
  return <Suspense><NewQuote /></Suspense>;
}
