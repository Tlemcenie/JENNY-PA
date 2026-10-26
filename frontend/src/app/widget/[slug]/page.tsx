import type { Metadata, Viewport } from "next";
import { WidgetChat } from "@/components/widget/widget-chat";

// mini-chat public, sans dashboard

export const metadata: Metadata = {
  title: { absolute: "Jenny · assistante virtuelle" },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
};

type Search = Record<string, string | string[] | undefined>;

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function WidgetPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Search>;
}) {
  const { slug } = await params;
  const sp = await searchParams;
  return (
    <WidgetChat
      slug={slug}
      color={one(sp.c)}
      theme={one(sp.t)}
      embedded={one(sp.embed) === "1"}
    />
  );
}
