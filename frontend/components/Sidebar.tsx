"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import NavIcon, { type NavIconName } from "@/components/NavIcons";
import { DASHBOARDS, PREDICT_NAV, RCA_NAV } from "@/lib/nav";

// Nav item look: slate-blue sidebar, active item darker with a red left edge.
const itemClass = (active: boolean) =>
  `flex w-full items-center gap-3 rounded-r-md border-l-4 px-3 py-2 text-left text-sm ${
    active
      ? "border-brand bg-nav-dark font-medium text-white"
      : "border-transparent text-slate-200 hover:bg-white/10"}`;

const sectionClass =
  "px-3 pb-1 pt-8 text-[11px] font-semibold uppercase tracking-wide text-slate-400";

function NavLink({ href, icon, active, children }: {
  href: string; icon: NavIconName; active: boolean; children: React.ReactNode;
}) {
  return (
    <Link href={href} className={itemClass(active)}>
      <NavIcon name={icon} />
      {children}
    </Link>
  );
}

function NavButton({ icon, onClick, children }: {
  icon: NavIconName; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button type="button" onClick={onClick} className={itemClass(false)}>
      <NavIcon name={icon} />
      {children}
    </button>
  );
}

export default function Sidebar() {
  const path = usePathname();

  return (
    <aside className="flex w-64 shrink-0 flex-col bg-nav">
      {/* Same height as the filter bar beside it (h-20 in layout.tsx). */}
      <div className="flex h-20 shrink-0 flex-col items-center justify-center bg-brand">
        <p className="text-2xl font-bold leading-none tracking-wider text-white">QBER</p>
        <p className="mt-1 text-xs text-red-100">For Hospitals</p>
      </div>

      <nav className="flex-1 overflow-y-auto p-3">
        <p className={`${sectionClass} !pt-4`}>Analytics</p>
        <div className="space-y-0.5">
          {DASHBOARDS.map((d) => (
            <NavLink key={d.slug} href={`/${d.slug}`}
                     icon={d.slug as NavIconName} active={path === `/${d.slug}`}>
              {d.title}
            </NavLink>
          ))}
          <NavLink href={`/${RCA_NAV.slug}`} icon="rca"
                   active={path === `/${RCA_NAV.slug}`}>
            {RCA_NAV.title}
          </NavLink>
          <NavLink href={`/${PREDICT_NAV.slug}`} icon="predict"
                   active={path === `/${PREDICT_NAV.slug}`}>
            {PREDICT_NAV.title}
          </NavLink>
        </div>

        <p className={sectionClass}>AI Insights</p>
        <div className="space-y-0.5">
          <NavLink href="/favorites" icon="favorites" active={path === "/favorites"}>
            Favorites
          </NavLink>
          {/* Opens the same chat panel as the floating button (ChatDock). */}
          <NavButton icon="ask"
                     onClick={() => window.dispatchEvent(new Event("qber:open-chat"))}>
            Ask QBER
          </NavButton>
        </div>

        <p className={sectionClass}>Actions</p>
        <div className="space-y-0.5">
          <NavLink href="/upload" icon="upload" active={path === "/upload"}>
            Upload
          </NavLink>
          <NavButton icon="refresh" onClick={() => window.location.reload()}>
            Refresh
          </NavButton>
          <NavLink href="/execute" icon="execute" active={path === "/execute"}>
            Execute
          </NavLink>
        </div>
      </nav>

      <div className="border-t border-white/10 px-5 py-3">
        <p className="text-[11px] leading-tight text-slate-400">
          Demo environment &middot; synthetic data
          <br />
          Jan 2025 &ndash; Dec 2026
        </p>
      </div>
    </aside>
  );
}
