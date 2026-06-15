"use client";

import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip } from "recharts";
import { channelLabel } from "@/lib/utils";
import type { ChannelStat } from "@/lib/api";

const COLORS = [
  "#FF7F6A",
  "#3B82F6",
  "#8B5CF6",
  "#10B981",
  "#F59E0B",
  "#EC4899",
  "#14B8A6",
];

export function ChannelDonut({ data }: { data: ChannelStat[] }) {
  const chartData = data.map((c) => ({ name: channelLabel(c.channel), value: c.count }));
  const total = chartData.reduce((s, d) => s + d.value, 0);

  return (
    <div className="flex items-center gap-4">
      <div className="relative w-32 h-32 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={chartData}
              dataKey="value"
              nameKey="name"
              innerRadius={40}
              outerRadius={62}
              paddingAngle={2}
              stroke="none"
            >
              {chartData.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                background: "var(--color-jenny-surface)",
                border: "1px solid var(--color-jenny-divider)",
                borderRadius: "0.75rem",
                fontSize: "0.8125rem",
                color: "var(--color-jenny-text)",
              }}
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span className="text-lg font-bold text-jenny-text tabular-nums">{total}</span>
          <span className="text-[10px] text-jenny-text-secondary">total</span>
        </div>
      </div>
      <div className="flex-1 min-w-0 space-y-1.5">
        {chartData.map((d, i) => (
          <div key={d.name} className="flex items-center gap-2 text-xs">
            <span
              className="w-2.5 h-2.5 rounded-full shrink-0"
              style={{ backgroundColor: COLORS[i % COLORS.length] }}
            />
            <span className="text-jenny-text-secondary truncate flex-1">{d.name}</span>
            <span className="font-medium text-jenny-text tabular-nums">{d.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
