"use client";

import { useParams, useRouter } from "next/navigation";
import { DocEditor, linesFromDoc } from "@/components/documents";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Alert, ErrorState, Loading } from "@/components/ui";
import { QUOTE_HEADER } from "@/features/fields";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/hooks";

type Q = Record<string, unknown> & { id: string; status: string; version: number; lines: Record<string, unknown>[]; number: string | null };

export default function EditQuote() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const { data: q, error, loading } = useQuery<Q>(`/sales/quotations/${id}`);
  if (loading && !q) return <Loading />;
  if (error || !q) return <ErrorState error={error} />;
  const header = Object.fromEntries(QUOTE_HEADER.map((f) => [f.name, q[f.name] ?? ""]));
  return (
    <>
      <PageHeader title={`Edit ${q.number ?? "draft quotation"}`} crumbs={[{ label: "Sales" }, { label: "Quotations", href: "/sales/quotations" }, { label: "Edit" }]} />
      {q.status === "sent" && <div className="mb-4"><Alert>This quotation was already sent. Saving creates a new revision and supersedes the sent one.</Alert></div>}
      <DocEditor title="Quotation details" headerFields={QUOTE_HEADER} initialHeader={header} initialLines={linesFromDoc(q.lines)}
        submitLabel={q.status === "sent" ? "Save as new revision" : "Save"}
        onSubmit={async (h, lines) => {
          const r = await api.patch<{ id: string }>(`/sales/quotations/${id}`, { ...h, lines, version: q.version });
          toast.success("Quotation saved");
          router.push(`/sales/quotations/${r.id}`);
        }} />
    </>
  );
}
