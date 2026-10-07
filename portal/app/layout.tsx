import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Suspense } from "react";
import Sidebar from "@/components/Sidebar";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Visual Memory",
  description: "Memories created from what your camera devices and uploaded videos have seen",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex h-full overflow-hidden">
        <Suspense fallback={<aside className="w-72 shrink-0 border-r border-zinc-800 bg-zinc-950" />}>
          <Sidebar />
        </Suspense>
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-5xl p-8">{children}</div>
        </main>
      </body>
    </html>
  );
}
