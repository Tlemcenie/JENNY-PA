import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { JennyAvatar } from "@/components/ui/jenny-avatar";

export const metadata = {
  title: "Conditions d'utilisation",
  description: "Les conditions d'utilisation du service Jenny.",
};

const PAGE_BG =
  "radial-gradient(ellipse at 70% 0%, rgba(255,127,106,0.14) 0%, transparent 50%), #0E0B14";

// Conditions d'utilisation — page réelle, plain-language, honnête sur le service.
export default function ConditionsPage() {
  return (
    <div className="min-h-full text-[#F4F1ED]" style={{ background: PAGE_BG }}>
      <div className="max-w-[760px] mx-auto px-6 py-12 md:py-20">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-[13px] text-[#F4F1ED]/60 hover:text-[#F4F1ED] transition-colors mb-10"
        >
          <ArrowLeft className="w-4 h-4" /> Retour à l&apos;accueil
        </Link>

        <div className="flex items-center gap-2.5 mb-8">
          <JennyAvatar size={34} tone="dark" />
          <span className="text-[18px] font-bold tracking-[-0.02em]">Jenny</span>
        </div>

        <h1 className="font-display text-[40px] md:text-[52px] leading-[1.05] tracking-[-0.02em] mb-4">
          Conditions d&apos;utilisation
        </h1>
        <p className="text-[14px] text-[#F4F1ED]/45 font-mono mb-10">
          Dernière mise à jour : 15 juin 2026
        </p>

        <div className="space-y-8 text-[15px] leading-[1.7] text-[#F4F1ED]/75">
          <section>
            <h2 className="text-[19px] font-semibold text-white mb-2">Objet</h2>
            <p>
              Jenny est un service d&apos;assistance par IA qui répond à vos clients et vous aide à
              gérer votre activité. En créant un compte, vous acceptez les présentes conditions.
            </p>
          </section>

          <section>
            <h2 className="text-[19px] font-semibold text-white mb-2">Votre compte</h2>
            <p>
              Vous êtes responsable de la confidentialité de vos identifiants et des actions
              effectuées depuis votre compte. Prévenez-nous en cas d&apos;accès non autorisé.
            </p>
          </section>

          <section>
            <h2 className="text-[19px] font-semibold text-white mb-2">Usage acceptable</h2>
            <p>
              Vous vous engagez à utiliser Jenny dans le respect de la loi et de vos clients :
              pas de contenu illicite, pas de spam, pas de détournement du service.
            </p>
          </section>

          <section>
            <h2 className="text-[19px] font-semibold text-white mb-2">Rôle de l&apos;IA</h2>
            <p>
              Jenny génère des réponses automatiquement et peut occasionnellement se tromper. Vous
              gardez le contrôle : vous pouvez relire, corriger et reprendre la main à tout moment.
              Les décisions importantes restent les vôtres.
            </p>
          </section>

          <section>
            <h2 className="text-[19px] font-semibold text-white mb-2">Disponibilité</h2>
            <p>
              Nous faisons de notre mieux pour assurer la continuité du service. Des interruptions
              (maintenance, incident) peuvent survenir. Le service évolue régulièrement.
            </p>
          </section>

          <section>
            <h2 className="text-[19px] font-semibold text-white mb-2">Essai &amp; résiliation</h2>
            <p>
              L&apos;essai est gratuit pendant 14 jours, sans engagement. Vous pouvez arrêter à tout
              moment depuis votre compte ; vos données sont alors supprimées sur demande.
            </p>
          </section>

          <section>
            <h2 className="text-[19px] font-semibold text-white mb-2">Droit applicable</h2>
            <p>
              Les présentes conditions sont régies par le droit français. Pour toute question :{" "}
              <a href="mailto:azsay12@gmail.com" className="text-jenny-coral hover:underline">
                azsay12@gmail.com
              </a>
              .
            </p>
          </section>

          <p className="text-[13px] text-[#F4F1ED]/40 pt-6 border-t border-white/10">
            Document rédigé en langage clair. Faites-le valider par votre conseil juridique avant
            une exploitation commerciale.
          </p>
        </div>
      </div>
    </div>
  );
}
