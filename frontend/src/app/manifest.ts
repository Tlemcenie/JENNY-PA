import type { MetadataRoute } from "next";

// pwa basique pour le gérant
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "Jenny · assistante virtuelle du salon",
    short_name: "Jenny",
    description:
      "Jenny, l'assistante virtuelle qui répond à vos clients et remplit votre agenda, 24h/24.",
    lang: "fr",
    dir: "ltr",
    start_url: "/dashboard",
    scope: "/",
    display: "standalone",
    orientation: "any",
    background_color: "#0E0B14",
    theme_color: "#111318",
    categories: ["business", "productivity"],
    icons: [
      { src: "/favicon.ico", sizes: "16x16 32x32 48x48", type: "image/x-icon" },
      { src: "/icon.png", sizes: "256x256", type: "image/png", purpose: "any" },
      { src: "/jenny.png", sizes: "1024x1024", type: "image/png", purpose: "any" },
    ],
    shortcuts: [
      { name: "Messages", url: "/conversations" },
      { name: "Agenda", url: "/calendar" },
    ],
  };
}
