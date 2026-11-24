export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <div className="hidden w-[42%] flex-col justify-between bg-gradient-to-br from-brand to-brand-hover p-10 text-white lg:flex">
        <div className="flex items-center gap-2 text-lg font-semibold">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-white font-bold text-brand">M</span> Manima One
        </div>
        <div>
          <h2 className="text-3xl font-semibold leading-tight">CRM, GST billing and inventory in one workspace.</h2>
          <p className="mt-3 text-white/85">Leads to quotations, orders, GST invoices, payments and stock — with every company&apos;s data strictly isolated.</p>
        </div>
        <p className="text-sm text-white/70">© Manima AI-Tech Solutions</p>
      </div>
      <div className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-md">{children}</div>
      </div>
    </div>
  );
}
