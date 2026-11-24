"use client";

import { Download } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { PageHeader } from "@/components/page";
import { Button, Card, CardHeader, ErrorState, Field, Input, Loading, Select, Stat, Tabs } from "@/components/ui";
import { qs } from "@/lib/api";
import { date, money, qty } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Row = Record<string, string | number | null>;

function Table({ cols, rows }: { cols: [string, string, ((r: Row) => React.ReactNode)?][]; rows: Row[] }) {
  if (!rows.length) return <p className="px-5 py-8 text-center text-sm text-muted">No data for this period.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-canvas text-left text-xs uppercase text-muted"><tr>{cols.map(([k, h]) => <th key={k} className="px-4 py-2">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-line">
          {rows.map((r, i) => <tr key={i}>{cols.map(([k, , f]) => <td key={k} className="px-4 py-2 tabular-nums">{f ? f(r) : (r[k] ?? "—")}</td>)}</tr>)}
        </tbody>
      </table>
    </div>
  );
}

const m = (k: string) => (r: Row) => money(r[k] as string);

function Sales({ from, to }: { from: string; to: string }) {
  const [group, setGroup] = useState("month");
  const { data, error, loading } = useQuery<{ data: Row[]; totals: Row }>(`/reports/sales${qs({ date_from: from, date_to: to, group })}`);
  if (error) return <ErrorState error={error} />;
  return (
    <div className="space-y-4">
      {data && <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Invoices" value={data.totals.count} /><Stat label="Taxable value" value={money(data.totals.taxable as string)} />
        <Stat label="GST" value={money(data.totals.tax as string)} /><Stat label="Total" value={money(data.totals.total as string)} tone="brand" />
      </div>}
      <Card>
        <CardHeader title="Invoiced sales" action={<Select className="h-8 w-40" value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Group by">
          <option value="month">By month</option><option value="customer">By customer</option><option value="item">By item</option></Select>} />
        {loading && !data ? <Loading /> : group === "item"
          ? <Table rows={data?.data ?? []} cols={[["label", "Item"], ["qty", "Qty", (r) => qty(r.qty as string)], ["taxable", "Taxable", m("taxable")], ["total", "Total", m("total")]]} />
          : <Table rows={data?.data ?? []} cols={[["label", group === "month" ? "Month" : "Customer"], ["count", "Invoices"], ["taxable", "Taxable", m("taxable")], ["tax", "GST", m("tax")], ["total", "Total", m("total")]]} />}
      </Card>
    </div>
  );
}

function Receivables() {
  const { data, error, loading } = useQuery<{ summary: Row; data: Row[] }>("/reports/receivables");
  if (error) return <ErrorState error={error} />;
  if (loading || !data) return <Loading />;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Stat label="Total outstanding" value={money(data.summary.total as string)} tone="brand" />
        <Stat label="Overdue" value={money(data.summary.overdue as string)} tone="red" />
        <Stat label="90+ days" value={money(data.summary.d90_plus as string)} />
      </div>
      <Card>
        <CardHeader title="Ageing by customer" />
        <Table rows={data.data} cols={[["customer", "Customer", (r) => <Link className="hover:text-brand" href={`/crm/accounts/${r.account_id}`}>{r.customer}</Link>],
          ["invoices", "Invoices"], ["current", "Not due", m("current")], ["d1_30", "1–30", m("d1_30")], ["d31_60", "31–60", m("d31_60")],
          ["d61_90", "61–90", m("d61_90")], ["d90_plus", "90+", m("d90_plus")], ["total", "Total", m("total")]]} />
      </Card>
    </div>
  );
}

function Gst({ from, to }: { from: string; to: string }) {
  const { data, error, loading } = useQuery<{ b2b: Row[]; b2c: Row[]; hsn: Row[]; notes: Row[]; totals: Row }>(`/reports/gst-summary${qs({ date_from: from, date_to: to })}`);
  if (error) return <ErrorState error={error} />;
  if (loading || !data) return <Loading />;
  const csv = (section: string) => `/api/v1/reports/gst-summary${qs({ date_from: from, date_to: to, format: "csv", section })}`;
  const dl = (s: string) => <a href={csv(s)}><Button size="sm" variant="secondary"><Download className="h-4 w-4" />CSV</Button></a>;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Taxable" value={money(data.totals.taxable as string)} /><Stat label="IGST" value={money(data.totals.igst as string)} />
        <Stat label="CGST" value={money(data.totals.cgst as string)} /><Stat label="SGST" value={money(data.totals.sgst as string)} />
        <Stat label="Invoices" value={data.totals.invoices} />
      </div>
      <Card><CardHeader title="B2B invoices (GSTR-1 Table 4)" action={dl("b2b")} />
        <Table rows={data.b2b} cols={[["number", "Invoice"], ["date", "Date", (r) => date(r.date as string)], ["gstin", "GSTIN"], ["name", "Name"], ["pos", "POS"],
          ["taxable", "Taxable", m("taxable")], ["igst", "IGST", m("igst")], ["cgst", "CGST", m("cgst")], ["sgst", "SGST", m("sgst")], ["total", "Total", m("total")]]} /></Card>
      <Card><CardHeader title="B2C summary by place of supply & rate" action={dl("b2c")} />
        <Table rows={data.b2c} cols={[["pos", "POS"], ["rate", "Rate", (r) => `${Number(r.rate)}%`], ["taxable", "Taxable", m("taxable")], ["igst", "IGST", m("igst")], ["cgst", "CGST", m("cgst")], ["sgst", "SGST", m("sgst")]]} /></Card>
      <Card><CardHeader title="HSN/SAC summary (Table 12)" action={dl("hsn")} />
        <Table rows={data.hsn} cols={[["hsn", "HSN/SAC"], ["unit", "UQC"], ["rate", "Rate", (r) => `${Number(r.rate)}%`], ["qty", "Qty", (r) => qty(r.qty as string)], ["taxable", "Taxable", m("taxable")], ["igst", "IGST", m("igst")], ["cgst", "CGST", m("cgst")], ["sgst", "SGST", m("sgst")]]} /></Card>
      <Card><CardHeader title="Credit / debit notes (Table 9B)" action={dl("notes")} />
        <Table rows={data.notes} cols={[["type", "Type"], ["number", "Number"], ["date", "Date", (r) => date(r.date as string)], ["taxable", "Taxable", m("taxable")], ["total", "Total", m("total")]]} /></Card>
    </div>
  );
}

function Inventory() {
  const { data, error, loading } = useQuery<{ by_category: Row[] }>("/reports/inventory");
  if (error) return <ErrorState error={error} />;
  if (loading || !data) return <Loading />;
  return <Card><CardHeader title="Stock valuation by category (at purchase price)" />
    <Table rows={data.by_category} cols={[["category", "Category"], ["items", "Items"], ["qty", "Qty on hand", (r) => qty(r.qty as string)], ["value", "Value", m("value")]]} /></Card>;
}

function Reports() {
  const { can } = useSession();
  const initial = useSearchParams().get("tab");
  const tabs = [
    can("reports.sales.read") && { key: "sales", label: "Sales" },
    can("reports.receivables.read") && { key: "receivables", label: "Receivables" },
    can("gst.report.read") && { key: "gst", label: "GST (GSTR-1)" },
    can("reports.inventory.read", "inventory.stock.read") && { key: "inventory", label: "Inventory" },
  ].filter(Boolean) as { key: string; label: string }[];
  const [tab, setTab] = useState(initial && tabs.some((t) => t.key === initial) ? initial : tabs[0]?.key);
  const now = new Date();
  const [from, setFrom] = useState(new Date(now.getFullYear(), now.getMonth() - (tab === "gst" ? 0 : 5), 1).toLocaleDateString("en-CA"));
  const [to, setTo] = useState(now.toLocaleDateString("en-CA"));
  if (!tabs.length) return <ErrorState error={{ message: "You do not have access to any reports." }} />;
  return (
    <>
      <PageHeader title="Reports" crumbs={[{ label: "Insights" }, { label: "Reports" }]} />
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <Tabs tabs={tabs} value={tab!} onChange={setTab} />
        {(tab === "sales" || tab === "gst") && (
          <div className="flex gap-2">
            <Field label="From"><Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label="To"><Input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
          </div>
        )}
      </div>
      {tab === "sales" && <Sales from={from} to={to} />}
      {tab === "receivables" && <Receivables />}
      {tab === "gst" && <Gst from={from} to={to} />}
      {tab === "inventory" && <Inventory />}
    </>
  );
}

export default function Page() {
  return <Suspense><Reports /></Suspense>;
}
