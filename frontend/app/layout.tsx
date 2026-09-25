import type { Metadata } from "next";
import { Atkinson_Hyperlegible_Next, Literata } from "next/font/google";
import "./globals.css";

// Atkinson Hyperlegible for readers who confuse letters; Literata for long reading on screens.
const atkinson = Atkinson_Hyperlegible_Next({
  variable: "--font-atkinson",
  subsets: ["latin", "latin-ext"],
});
const literata = Literata({
  variable: "--font-literata",
  subsets: ["latin", "latin-ext", "greek"],
});

export const metadata: Metadata = {
  title: "GenAI4ED",
  description: "Personal AI tutors, with the teacher in charge. Internal prototype.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en-GB" className={`${atkinson.variable} ${literata.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col font-sans">{children}</body>
    </html>
  );
}
