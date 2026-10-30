"use client";

import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { inrCompact } from "@/lib/format";

const COLORS = ["#3d6479", "#c0392b", "#2f54d4", "#5bbcd6",
                "#e08a1e", "#7b4fd1", "#2a9d8f", "#8fe3f5"];

interface Slice {
  name: string;
  value: number;
}

export default function DrilldownDonut({
  title, data, onClose,
}: { title: string; data: Slice[]; onClose: () => void }) {
  const total = data.reduce((sum, d) => sum + d.value, 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-lg rounded-lg bg-white shadow-xl">
        <div className="flex items-center justify-between bg-nav px-5 py-3 rounded-t-lg">
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          <button onClick={onClose} className="text-white/80 hover:text-white">✕</button>
        </div>
        <div className="p-4">
          {data.length === 0 ? (
            <p className="py-10 text-center text-sm text-slate-500">
              No data for this month.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={320}>
              <PieChart>
                <Tooltip formatter={(v) => inrCompact(Number(v))}
                         contentStyle={{ color: "#0f172a" }}
                         labelStyle={{ color: "#0f172a" }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Pie data={data} dataKey="value" nameKey="name"
                     innerRadius={60} outerRadius={100}
                     label={({ name, percent }) => `${name} ${(percent! * 100).toFixed(1)}%`}>
                  {data.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="flex items-center justify-between border-t border-slate-100 px-5 py-3">
          <span className="text-sm font-semibold text-nav">
            Total: {inrCompact(total)}
          </span>
          <button onClick={onClose}
                  className="rounded bg-brand px-4 py-1.5 text-sm text-white hover:bg-brand-dark">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}