import DashboardPage from "@/components/DashboardPage";
import { DASHBOARDS } from "@/lib/nav";

const meta = DASHBOARDS.find((d) => d.slug === "sob-opportunities")!;

export default function Page() {
  return <DashboardPage slug={meta.slug} title={meta.title} />;
}
