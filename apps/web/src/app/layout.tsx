import type { Metadata } from "next";
import { ToastProvider } from "@/components/toast";
import { SessionProvider } from "@/lib/session";
import "./globals.css";

export const metadata: Metadata = { title: "Manima One", description: "CRM + ERP for growing Indian businesses" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN">
      <body className="antialiased">
        <SessionProvider>
          <ToastProvider>{children}</ToastProvider>
        </SessionProvider>
      </body>
    </html>
  );
}
