"use client";

import { useState } from "react";
import { FormFields, type FieldDef } from "@/components/form";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Alert, Button, Card, CardHeader, ErrorState, Loading } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const PROFILE: FieldDef[] = [
  { name: "display_name", label: "Company name", required: true, colSpan: 2 },
  { name: "email", label: "Company email", type: "email" },
  { name: "phone", label: "Phone" },
  { name: "website", label: "Website" },
  { name: "pan", label: "PAN" },
  { name: "state_code", label: "State", type: "state" },
  { name: "logo_url", label: "Logo URL" },
  { name: "address.line1", path: ["address", "line1"], label: "Address", colSpan: 2 },
  { name: "address.city", path: ["address", "city"], label: "City" },
  { name: "address.pincode", path: ["address", "pincode"], label: "PIN code" },
];
const PREFS: FieldDef[] = [
  { name: "fiscal_year_start_month", label: "Financial year starts", type: "select", required: true, options: MONTHS.map((mo, i) => ({ value: String(i + 1), label: mo })) },
  { name: "date_format", label: "Date format", type: "select", required: true, options: ["DD/MM/YYYY", "YYYY-MM-DD", "DD-MMM-YYYY"].map((v) => ({ value: v, label: v })) },
  { name: "quote_validity_days", label: "Quotation validity (days)", type: "number" },
  { name: "discount_approval_limit", label: "Discount approval above (%)", type: "number", hint: "Quotation lines above this discount need approval" },
  { name: "allow_negative_stock", label: "Allow negative stock", type: "checkbox" },
  { name: "invoice_terms", label: "Default invoice terms", type: "textarea" },
];

export default function CompanySettings() {
  const { data, error, loading, reload } = useQuery<Record<string, unknown>>("/tenant/settings");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;
  // Keyed by version so a saved reload reseeds the form from the server copy.
  return <CompanyForm key={String(data.version ?? data.updated_at ?? "")} data={data} reload={reload} />;
}

function CompanyForm({ data, reload }: { data: Record<string, unknown>; reload: () => void }) {
  const { can, refresh } = useSession();
  const toast = useToast();
  const [v, setV] = useState<Record<string, unknown>>(() => ({
    ...data,
    fiscal_year_start_month: String(data.fiscal_year_start_month),
    address: data.address ?? {},
  }));
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const editable = can("core.settings.manage");
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const body = { ...v, fiscal_year_start_month: Number(v.fiscal_year_start_month), state_code: v.state_code || null, pan: v.pan || null, email: v.email || null };
      await api.patch("/tenant/settings", body); toast.success("Company settings saved"); reload(); refresh();
    } catch (e) { setErr(e as ApiError); } finally { setBusy(false); }
  };
  return (
    <>
      <PageHeader title="Company profile" crumbs={[{ label: "Settings" }, { label: "Company" }]} actions={editable && <Button onClick={save} loading={busy}>Save changes</Button>} />
      {err && <div className="mb-4"><Alert tone="red">{err.message}</Alert></div>}
      <fieldset disabled={!editable} className="space-y-6">
        <Card><CardHeader title="Company" /><div className="p-5"><FormFields fields={PROFILE} values={v} onChange={setV} errors={err?.fieldErrors() ?? {}} /></div></Card>
        <Card><CardHeader title="Preferences" /><div className="p-5"><FormFields fields={PREFS} values={v} onChange={setV} errors={err?.fieldErrors() ?? {}} /></div></Card>
      </fieldset>
    </>
  );
}
