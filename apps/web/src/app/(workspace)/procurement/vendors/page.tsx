"use client";

import { ResourcePage } from "@/components/page";
import { VENDOR_FIELDS } from "@/features/fields";

type V = { id: string; name: string; gstin: string | null; state_code: string | null; contact_person: string | null; email: string | null; phone: string | null; payment_terms_days: number };

export default function VendorsPage() {
  return (
    <ResourcePage<V> title="Vendors" nounSingular="vendor" crumbs={[{ label: "Operations" }, { label: "Vendors" }]} endpoint="/procurement/vendors"
      module="procurement" fields={VENDOR_FIELDS} createPerm="procurement.vendor.manage" updatePerm="procurement.vendor.manage" deletePerm="procurement.vendor.manage"
      defaults={{ payment_terms_days: 30, address: {} }}
      columns={[
        { key: "name", header: "Vendor", render: (r) => <span className="font-medium">{r.name}</span> },
        { key: "gstin", header: "GSTIN", render: (r) => r.gstin ?? "—" },
        { key: "state_code", header: "State", render: (r) => r.state_code ?? "—" },
        { key: "contact_person", header: "Contact", render: (r) => r.contact_person ?? "—" },
        { key: "email", header: "Email", render: (r) => r.email ?? "—" },
        { key: "payment_terms_days", header: "Terms", render: (r) => `${r.payment_terms_days} days` },
      ]} />
  );
}
