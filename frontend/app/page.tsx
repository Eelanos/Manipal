import { redirect } from "next/navigation";

// The Overview page was removed; the bare URL opens the first dashboard.
export default function Home() {
  redirect("/inventory-analysis");
}
