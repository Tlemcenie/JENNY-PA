import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { JennyAvatar } from "@/components/ui/jenny-avatar";

export const metadata = {
  title: "Confidentialité",
  description: "Comment Jenny traite et protège vos données et celles de vos clients.",
};

const PAGE_BG =
  "radial-gradient(ellipse at 70% 0%, rgba(255,127,106,0.14) 0%, transparent 50%), #0E0B14";

// Politique de confidentialité — page réelle, plain-language, reflétant le
// comportement effectif de l'app (RGPD, hébergement France, export/suppression).
export default function ConfidentialitePage() {
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
          Confidentialité
        </h1>
        <p className="text-[14px] text-[#F4F1ED]/45 font-mono mb-10">
          Dernière mise à jour : 15 juin 2026
        </p>

        <div className="space-y-8 text-[15px] leading-[1.7] text-[#F4F1ED]/75">
          <section>
            <h2 className="text-[19px] font-semibold text-white mb-2">En bref</h2>
            <p>
              Jenny est une assistante qui répond à vos clients sur vos canaux. Pour cela, elle
              traite les messages et les coordonnées de vos clients <strong>pour votre compte</strong>.
              Vos données et celles de vos clients sont hébergées en France et ne sont jamais
              revendues.
            </p>
          </section>

          <section>
            <h2 className="text-[19px] font-semibold text-white mb-2">Données traitées</h2>
            <ul className="list-disc pl-5 space-y-1.5">
              <li>Votre compte : nom, email, mot de passe (chiffré).</li>
              <li>Vos clients : nom, téléphone, email, identifiants de messagerie, historique des conversations et des rendez-vous.</li>
              <li>Le contenu échangé avec Jenny, utilisé pour répondre et améliorer le service.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-[19px] font-semibold text-white mb-2">Finalités</h2>
            <p>
              Répondre aux messages, gérer les rendez-vous, vous fournir des statistiques, et faire
              fonctionner le service. Aucune donnée n&apos;est utilisée à des fins publicitaires.
            </p>
          </section>

          <section>
            <h2 className="text-[19px] font-semibold text-white mb-2">Hébergement &amp; sécurité</h2>
            <p>
              Hébergement en France. Accès restreint, mots de passe chiffrés, connexions sécurisées.
              Conforme au RGPD.
            </p>
          </section>

          <section>
            <h2 className="text-[19px] font-semibold text-white mb-2">Vos droits (RGPD)</h2>
            <p>
              Vous pouvez à tout moment, depuis votre tableau de bord, <strong>exporter</strong> ou
              <strong> supprimer</strong> l&apos;ensemble des données d&apos;un client. Pour exercer
              vos propres droits (accès, rectification, suppression, portabilité), écrivez-nous à{" "}
              <a href="mailto:azsay12@gmail.com" className="text-jenny-coral hover:underline">
                azsay12@gmail.com
              </a>
              .
            </p>
          </section>

          <section>
            <h2 className="text-[19px] font-semibold text-white mb-2">Conservation</h2>
            <p>
              Les données sont conservées tant que votre compte est actif, puis supprimées sur
              demande ou à la fermeture du compte.
            </p>
          </section>

          <p className="text-[13px] text-[#F4F1ED]/40 pt-6 border-t border-white/10">
            Ce document décrit en langage clair la manière dont Jenny traite les données. Adaptez-le
            avec votre conseil juridique avant une mise en production commerciale.
          </p>
        </div>
      </div>
    </div>
  );
}
