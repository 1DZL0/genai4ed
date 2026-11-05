import type { Metadata } from "next";
import { Fraunces, Nunito } from "next/font/google";
import "./globals.css";

// Nunito for everything read and written: open, rounded letters at a size a classroom screen
// can carry. Fraunces for titles: a warm serif with some character, set at its text optical
// size so it stays calm.
const nunito = Nunito({
  variable: "--font-body",
  subsets: ["latin", "latin-ext"],
  weight: "variable",
});
const fraunces = Fraunces({
  variable: "--font-display",
  subsets: ["latin", "latin-ext"],
  weight: "variable",
  axes: ["opsz", "SOFT"],
});

export const metadata: Metadata = {
  title: "GenAI4ED",
  description: "Personal AI tutors, with the teacher in charge. Internal prototype.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en-GB" className={`${nunito.variable} ${fraunces.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col font-sans">{children}</body>
    </html>
  );
}
