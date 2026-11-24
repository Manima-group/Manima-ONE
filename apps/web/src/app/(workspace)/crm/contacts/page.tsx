"use client";

import Link from "next/link";
import { ResourcePage } from "@/components/page";
import { CONTACT_FIELDS } from "@/features/fields";

type Contact = { id: string; name: string; account_id: string | null; account_name: string | null; email: string | null; phone: string | null; designation: string | null };

export default function ContactsPage() {
  return (
    <ResourcePage<Contact> title="Contacts" nounSingular="contact" crumbs={[{ label: "CRM" }, { label: "Contacts" }]} endpoint="/crm/contacts"
      module="crm" fields={CONTACT_FIELDS} createPerm="crm.account.create" updatePerm="crm.account.update" deletePerm="crm.account.delete"
      columns={[
        { key: "name", header: "Name", render: (r) => <span className="font-medium">{r.name}</span> },
        { key: "account_name", header: "Customer", render: (r) => r.account_id ? <Link className="hover:text-brand" href={`/crm/accounts/${r.account_id}`}>{r.account_name}</Link> : "—" },
        { key: "designation", header: "Designation", render: (r) => r.designation ?? "—" },
        { key: "email", header: "Email", render: (r) => r.email ?? "—" },
        { key: "phone", header: "Phone", render: (r) => r.phone ?? "—" },
      ]} />
  );
}
