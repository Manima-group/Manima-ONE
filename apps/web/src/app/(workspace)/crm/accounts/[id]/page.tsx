"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ActivityPanel } from "@/components/activity-panel";
import { DataTable } from "@/components/data-table";
import { FormDialog } from "@/components/form";
import { PageHeader } from "@/components/page";
import { useToast } from "@/components/toast";
import { Button, Card, CardHeader, ErrorState, Loading, StatusBadge, Tabs } from "@/components/ui";
import { ACCOUNT_FIELDS, CONTACT_FIELDS } from "@/features/fields";
import { api } from "@/lib/api";
import { date, label, money } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Contact = { id: string; name: string; email: string | null; phone: string | null; designation: string | null; is_primary: boolean };
type Account = Record<string, unknown> & { id: string; name: string; type: string; gstin: string | null; pan: string | null; state_code: string | null;
  email: string | null; phone: string | null; payment_terms_days: number; credit_limit: string; billing_address: Record<string, string>; contacts: Contact[]; notes: string | null };

export default function AccountDetail() {
  const { id } = useParams<{ id: string }>();
  const { can, writable } = useSession();
  const toast = useToast();
  const { data: a, error, loading, reload } = useQuery<Account>(`/crm/accounts/${id}`);
  const [edit, setEdit] = useState(false);
  const [contact, setContact] = useState(false);
  const [tab, setTab] = useState("activity");
  if (loading && !a) return <Loading />;
  if (error || !a) return <ErrorState error={error} onRetry={reload} />;
  const tabs = [{ key: "activity", label: "Activity" }];
  if (can("sales.quotation.read_all", "sales.quotation.read_own")) tabs.push({ key: "quotes", label: "Quotations" });
  if (can("invoicing.invoice.read")) tabs.push({ key: "invoices", label: "Invoices" });
  if (can("payments.payment.read")) tabs.push({ key: "payments", label: "Payments" });
  return (
    <>
      <PageHeader title={a.name} subtitle={a.gstin ? `GSTIN ${a.gstin}` : "Unregistered (B2C)"} crumbs={[{ label: "CRM" }, { label: "Customers", href: "/crm/accounts" }, { label: a.name }]}
        actions={<>
          {can("sales.quotation.create") && writable("sales") && <Link href={`/sales/quotations/new?account=${a.id}`}><Button variant="secondary">New quotation</Button></Link>}
          {can("invoicing.invoice.create") && writable("invoicing") && <Link href={`/billing/invoices/new?account=${a.id}`}><Button variant="secondary">New invoice</Button></Link>}
          {can("crm.account.update") && writable("crm") && <Button onClick={() => setEdit(true)}>Edit</Button>}
        </>} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6">
          <Card>
            <CardHeader title="Profile" action={<span className="text-xs text-muted">{label(a.type)}</span>} />
            <dl className="divide-y divide-line text-sm">
              {[["Email", a.email], ["Phone", a.phone], ["PAN", a.pan], ["State", a.state_code], ["Payment terms", `${a.payment_terms_days} days`],
                ["Credit limit", money(a.credit_limit)], ["City", a.billing_address?.city]].filter(([, v]) => v).map(([k, v]) => (
                <div key={String(k)} className="flex justify-between px-5 py-2.5"><dt className="text-muted">{k}</dt><dd>{String(v)}</dd></div>
              ))}
            </dl>
          </Card>
          <Card>
            <CardHeader title="Contacts" action={can("crm.account.create") && writable("crm") && <Button size="sm" variant="secondary" onClick={() => setContact(true)}>Add</Button>} />
            <ul className="divide-y divide-line">
              {!a.contacts.length && <li className="px-5 py-4 text-sm text-muted">No contacts yet.</li>}
              {a.contacts.map((c) => (
                <li key={c.id} className="px-5 py-2.5 text-sm">
                  <p className="font-medium">{c.name} {c.is_primary && <span className="text-xs text-brand">· primary</span>}</p>
                  <p className="text-xs text-muted">{[c.designation, c.email, c.phone].filter(Boolean).join(" · ")}</p>
                </li>
              ))}
            </ul>
          </Card>
        </div>
        <div className="space-y-4 lg:col-span-2">
          <Tabs tabs={tabs} value={tab} onChange={setTab} />
          {tab === "activity" && <ActivityPanel relatedType="account" relatedId={a.id} />}
          {tab === "quotes" && <DataTable<{ id: string; number: string | null; status: string; issue_date: string; grand_total: string }>
            endpoint={`/sales/quotations?account_id=${a.id}`} rowHref={(r) => `/sales/quotations/${r.id}`}
            columns={[{ key: "number", header: "Number", render: (r) => r.number ?? "Draft" }, { key: "issue_date", header: "Date", render: (r) => date(r.issue_date) },
              { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> }, { key: "grand_total", header: "Total", align: "right", render: (r) => money(r.grand_total) }]} />}
          {tab === "invoices" && <DataTable<{ id: string; number: string | null; document_status: string; payment_status: string; invoice_date: string; grand_total: string; amount_due: string }>
            endpoint={`/billing/invoices?account_id=${a.id}`} rowHref={(r) => `/billing/invoices/${r.id}`}
            columns={[{ key: "number", header: "Number", render: (r) => r.number ?? "Draft" }, { key: "invoice_date", header: "Date", render: (r) => date(r.invoice_date) },
              { key: "document_status", header: "Status", render: (r) => <StatusBadge status={r.document_status} /> },
              { key: "payment_status", header: "Payment", render: (r) => <StatusBadge status={r.payment_status} /> },
              { key: "grand_total", header: "Total", align: "right", render: (r) => money(r.grand_total) }, { key: "amount_due", header: "Due", align: "right", render: (r) => money(r.amount_due) }]} />}
          {tab === "payments" && <DataTable<{ id: string; number: string; method: string; received_on: string; amount: string }>
            endpoint={`/billing/payments?account_id=${a.id}`} rowHref={(r) => `/billing/payments/${r.id}`}
            columns={[{ key: "number", header: "Receipt" }, { key: "received_on", header: "Date", render: (r) => date(r.received_on) },
              { key: "method", header: "Method", render: (r) => label(r.method) }, { key: "amount", header: "Amount", align: "right", render: (r) => money(r.amount) }]} />}
        </div>
      </div>
      <FormDialog open={edit} onClose={() => setEdit(false)} title="Edit customer" fields={ACCOUNT_FIELDS} initial={a} wide
        submit={async (v) => { const { contacts: _c, ...rest } = v as Account; void _c; await api.patch(`/crm/accounts/${id}`, rest); toast.success("Customer updated"); reload(); }} />
      <FormDialog open={contact} onClose={() => setContact(false)} title="New contact" fields={CONTACT_FIELDS.filter((f) => f.name !== "account_id")} initial={{}}
        submit={async (v) => { await api.post("/crm/contacts", { ...v, account_id: a.id }); toast.success("Contact added"); reload(); }} />
    </>
  );
}
