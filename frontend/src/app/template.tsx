"use client";

import { motion } from "framer-motion";

// Template RACINE de l'App Router : remonté à chaque changement de 1er segment
// (login, register, admin, landing, /book…), il rejoue une entrée discrète sur
// TOUTES les pages — y compris celles hors dashboard.
//
// ⚠️ Double-fade : `(dashboard)/template.tsx` applique déjà `pageTransition`
// (opacity + y). Pour éviter qu'une page dashboard ne soit animée DEUX fois
// (ici puis dans le template du groupe), ce template racine reste volontairement
// minimal : un simple fondu très court, sans translation. Les deux se cumulent
// alors de façon imperceptible (l'opacité racine est quasi instantanée pendant
// que le glissement du dashboard porte le ressenti). Ne pas y ajouter de `y` /
// `scale` sous peine de re-déclencher un double mouvement visible.
export default function RootTemplate({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className="contents"
    >
      {children}
    </motion.div>
  );
}
