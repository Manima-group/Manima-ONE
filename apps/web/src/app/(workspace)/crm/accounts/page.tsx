"use client";

import { ResourcePage } from "@/components/page";
import { ACCOUNT_FIELDS } from "@/features/fields";
import { label } from "@/lib/format";

type Account = { id: string; name: string; type: string; gstin: string | null; state_code: string | null; email: string | null; phone: string | null };

export default function AccountsPage() {
  return (
    <ResourcePage<Account> title="Customers" nounSingular="customer" crumbs={[{ label: "CRM" }, { label: "Customers" }]}
      endpoint="/crm/accounts" module="crm" fields={ACCOUNT_FIELDS} createPerm="crm.account.create" updatePerm="crm.account.update"
      deletePerm="crm.account.delete" rowHref={(r) => `/crm/accounts/${r.id}`}
      defaults={{ type: "customer", payment_terms_days: 30, credit_limit: "0", billing_address: {} }}
      filters={[{ key: "type", label: "Type", options: ["customer", "prospect", "partner"].map((v) => ({ value: v, label: label(v) })) }]}
      columns={[
        { key: "name", header: "Name" },
        { key: "type", header: "Type", render: (r) => label(r.type) },
        { key: "gstin", header: "GSTIN", render: (r) => r.gstin ?? <span className="text-muted">Unregistered</span> },
        { key: "state_code", header: "State", render: (r) => r.state_code ?? "—" },
        { key: "email", header: "Email", render: (r) => r.email ?? "—" },
        { key: "phone", header: "Phone", render: (r) => r.phone ?? "—" },
      ]} />
  );
}
