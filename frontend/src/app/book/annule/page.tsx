// page retour Stripe : paiement annulé
const PAGE_BG =
  "radial-gradient(ellipse at 70% -10%, rgba(255,127,106,0.20) 0%, transparent 52%), radial-gradient(ellipse at 0% 90%, rgba(114,132,168,0.12) 0%, transparent 50%), #0E0B14";

export default async function DepositCancelPage({
  searchParams,
}: {
  searchParams: Promise<{ dep?: string | string[] }>;
}) {
  // id du RDV, juste pour l'affichage
  const params = await searchParams;
  const dep = typeof params.dep === "string" ? params.dep : "";

  return (
    <div
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
            — Paiement annulé —
          </div>
          <h1 className="font-display font-normal text-[34px] leading-[1.05] tracking-[-0.02em] mb-3">
            Paiement annulé
          </h1>
          <p className="text-[15px] leading-[1.6] text-[#F4F1ED]/70">
            Le paiement n'a pas abouti, ton créneau n'est donc pas encore
            confirmé. Tu peux réessayer quand tu veux.
          </p>
          {dep && (
            <p className="mt-6 font-mono text-[11px] tracking-[0.12em] text-[#F4F1ED]/35">
              réf. {dep}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
