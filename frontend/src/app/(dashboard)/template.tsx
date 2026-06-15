"use client";

import { motion } from "framer-motion";
import { pageTransition } from "@/lib/motion";

// `template.tsx` est remonté à chaque navigation (clé unique par segment),
// ce qui rejoue l'animation d'entrée : le contenu transitionne pendant que
// la sidebar et la topbar restent fixes.
export default function DashboardTemplate({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <motion.div
      variants={pageTransition}
      initial="hidden"
      animate="show"
      className="h-full"
    >
      {children}
    </motion.div>
  );
}
