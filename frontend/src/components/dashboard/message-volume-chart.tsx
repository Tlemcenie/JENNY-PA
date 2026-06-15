"use client";

import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { format } from "date-fns";
import { fr } from "date-fns/locale";
import type { DailyStat } from "@/lib/api";

interface Props {
  data: DailyStat[];
  days: number;
}

export function MessageVolumeChart({ data, days }: Props) {
  const chartData = data.map((d) => ({
    count: d.count,
    label: format(new Date(d.date + "T00:00:00"), days <= 7 ? "EEE" : "dd/MM", { locale: fr }),
  }));

  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={chartData} margin={{ top: 8, right: 4, left: -22, bottom: 0 }}>
        <defs>
          <linearGradient id="jennyBar" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#FF7F6A" />
            <stop offset="100%" stopColor="#FFB4A4" />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-jenny-divider)" />
        <XAxis
          dataKey="label"
          tick={{ fontSize: 10, fill: "var(--color-jenny-text-secondary)" }}
          tickLine={false}
          axisLine={false}
          interval={days <= 7 ? 0 : Math.max(1, Math.floor(days / 8))}
        />
        <YAxis
          tick={{ fontSize: 10, fill: "var(--color-jenny-text-secondary)" }}
          tickLine={false}
          axisLine={false}
          allowDecimals={false}
          width={26}
        />
        <Tooltip
          cursor={{ fill: "var(--color-jenny-coral)", opacity: 0.08 }}
          contentStyle={{
            background: "var(--color-jenny-surface)",
            border: "1px solid var(--color-jenny-divider)",
            borderRadius: "0.75rem",
            fontSize: "0.8125rem",
            color: "var(--color-jenny-text)",
            boxShadow: "0 8px 24px rgba(0,0,0,0.12)",
          }}
          labelStyle={{ color: "var(--color-jenny-text-secondary)" }}
        />
        <Bar
          dataKey="count"
          name="Messages"
          fill="url(#jennyBar)"
          radius={[4, 4, 0, 0]}
          maxBarSize={48}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
