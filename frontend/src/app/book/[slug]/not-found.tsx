// salon inconnu ou désactivé
const PAGE_BG =
  "radial-gradient(ellipse at 70% -10%, rgba(255,127,106,0.20) 0%, transparent 52%), radial-gradient(ellipse at 0% 90%, rgba(114,132,168,0.12) 0%, transparent 50%), #0E0B14";

export default function BookingNotFound() {
  return (
    <main
      className="min-h-full w-full overflow-y-auto text-[#F4F1ED]"
      style={{ background: PAGE_BG, fontFamily: "var(--font-sans)" }}
    >
      <div className="min-h-full flex flex-col items-center justify-center px-4 py-16">
        <div
          className="w-full max-w-[480px] rounded-[24px] p-8 text-center"
          style={{
            background: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.09)",
            boxShadow: "0 24px 60px rgba(0,0,0,0.35)",
          }}
        >
          <div className="font-mono text-[11px] tracking-[0.22em] uppercase text-[#F4F1ED]/45 mb-4">
            — Lien introuvable —
          </div>
          <h1 className="font-display font-normal text-[34px] leading-[1.05] tracking-[-0.02em] mb-3">
            Page de réservation introuvable
          </h1>
          <p className="text-[15px] leading-[1.6] text-[#F4F1ED]/70">
            Ce lien n&apos;existe pas ou n&apos;est plus actif. Vérifiez l&apos;adresse, ou contactez
            directement le salon pour prendre rendez-vous.
          </p>
        </div>
      </div>
    </main>
  );
}
