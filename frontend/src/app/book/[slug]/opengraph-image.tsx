import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { ImageResponse } from "next/og";
import { getPublicBooking } from "@/lib/api-public";

// image de partage du salon

export const alt = "Prendre rendez-vous en ligne";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const revalidate = 600;

let mascot: Promise<string | null> | null = null;

// mascotte en data url
function loadMascot(): Promise<string | null> {
  if (!mascot) {
    mascot = readFile(join(process.cwd(), "public", "jenny.png"))
      .then((buf) => `data:image/png;base64,${buf.toString("base64")}`)
      .catch(() => null);
  }
  return mascot;
}

export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const [res, logo] = await Promise.all([getPublicBooking(slug), loadMascot()]);
  // api coupée : pas d'image en cache
  if (res.status === "error") throw new Error("API de réservation injoignable");
  const name = res.status === "ok" ? res.info.name : "Réservation en ligne";
  const nameSize = name.length > 34 ? 64 : name.length > 20 ? 80 : 96;

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          position: "relative",
          background: "#0E0B14",
          backgroundImage:
            "radial-gradient(circle at 78% 18%, rgba(255,127,106,0.32) 0%, rgba(14,11,20,0) 55%)",
          color: "#F4F1ED",
          padding: "72px 80px",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", width: 760 }}>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 24, letterSpacing: 6, color: "#FF7F6A", marginBottom: 28 }}>
              RÉSERVATION EN LIGNE
            </div>
            <div style={{ fontSize: nameSize, lineHeight: 1.05, letterSpacing: -2 }}>{name}</div>
            <div style={{ fontSize: 30, color: "rgba(244,241,237,0.65)", marginTop: 28 }}>
              Choisissez votre créneau en quelques secondes, 24h/24.
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", fontSize: 24, color: "rgba(244,241,237,0.55)" }}>
            <div
              style={{
                display: "flex",
                background: "#FF7F6A",
                color: "#FFFFFF",
                borderRadius: 999,
                padding: "12px 28px",
                fontSize: 26,
                marginRight: 24,
              }}
            >
              Réserver
            </div>
            Propulsé par Jenny
          </div>
        </div>
        {logo && (
          <img
            src={logo}
            alt=""
            width={340}
            height={340}
            style={{ position: "absolute", right: 70, bottom: 60 }}
          />
        )}
      </div>
    ),
    { ...size }
  );
}
