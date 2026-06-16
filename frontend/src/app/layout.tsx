import type { Metadata } from "next";
import { Inter, Instrument_Serif, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";
import { ToastProvider } from "@/components/ui/toast";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

// Police éditoriale (titres hero, accents en italique) — DA Jenny Front.
const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-display",
  display: "swap",
});

// Police mono pour badges, labels de section, raccourcis — DA Jenny Front.
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000"),
  title: {
    default: "Jenny — Chaque message client, une opportunité",
    template: "%s · Jenny",
  },
  description:
    "Jenny est l'assistante IA qui répond à vos clients sur WhatsApp, Instagram et Email — 24/7, dans votre ton, avec votre catalogue.",
  applicationName: "Jenny",
  keywords: [
    "assistant IA",
    "service client",
    "WhatsApp Business",
    "Instagram",
    "support multicanal",
    "automatisation",
  ],
  openGraph: {
    title: "Jenny — Chaque message client, une opportunité",
    description:
      "L'assistante IA qui répond à vos clients sur tous vos canaux, dans votre ton, 24/7.",
    siteName: "Jenny",
    locale: "fr_FR",
    type: "website",
    images: [{ url: "/jenny.png", width: 512, height: 512, alt: "Jenny" }],
  },
  twitter: {
    card: "summary",
    title: "Jenny — Chaque message client, une opportunité",
    description: "L'assistante IA qui répond à vos clients sur tous vos canaux, 24/7.",
    images: ["/jenny.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="fr"
      className={`${inter.variable} ${instrumentSerif.variable} ${jetbrainsMono.variable} h-full`}
      suppressHydrationWarning
    >
      <head>
        {/* Applique le thème avant le premier paint pour éviter le flash clair/sombre */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem('jenny-theme');if(t==='dark'||((!t||t==='system')&&window.matchMedia('(prefers-color-scheme:dark)').matches)){document.documentElement.classList.add('dark')}var a=localStorage.getItem('jenny-accent');if(a&&/^#[0-9a-fA-F]{6}$/.test(a)){var R=parseInt(a.slice(1,3),16),G=parseInt(a.slice(3,5),16),B=parseInt(a.slice(5,7),16),h=function(c){return('0'+Math.round(c).toString(16)).slice(-2)},m=function(tg,p){return'#'+h(R+(tg-R)*p)+h(G+(tg-G)*p)+h(B+(tg-B)*p)},s=document.documentElement.style;s.setProperty('--color-jenny-coral',a);s.setProperty('--color-jenny-coral-light',m(255,0.45));s.setProperty('--color-jenny-coral-dark',m(0,0.12))}}catch(e){}`,
          }}
        />
      </head>
      {/* suppressHydrationWarning : certaines extensions navigateur (ClickUp, Grammarly…)
          modifient <body> avant l'hydratation React → faux avertissements rouges en console.
          Inoffensif, mais on les fait taire pour ne pas inquiéter. */}
      <body className="h-full antialiased" suppressHydrationWarning>
        <AuthProvider>
          <ToastProvider>{children}</ToastProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
