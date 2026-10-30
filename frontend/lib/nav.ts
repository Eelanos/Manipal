// Single source of truth for the five dashboards. The sidebar and each route
// read from here, so adding a sixth dashboard is a one-entry change.

export interface NavItem {
  slug: string;          // matches the API path AND the route path
  title: string;
}

export const DASHBOARDS: NavItem[] = [
  {
    slug: "inventory-analysis",
    title: "Inventory Analysis",
  },
  {
    slug: "consumption",
    title: "Consumption",
  },
  {
    slug: "formulary-compliance",
    title: "Formulary Compliance",
  },
  {
    slug: "sob-opportunities",
    title: "SOB Opportunities",
  },
  {
    slug: "sob-compliance",
    title: "SOB Compliance",
  },
];

// The RCA tab. Deliberately NOT in DASHBOARDS: that list drives the sidebar
// dashboard links and the /api/<slug> fetches, and RCA has no backend
// endpoint yet.
export const RCA_NAV = { slug: "rca", title: "RCA" };

// The Predictive Analysis tab (below RCA). Like RCA it is deliberately NOT in
// DASHBOARDS: it has its own endpoints (/api/predict/*) and its own page.
export const PREDICT_NAV = { slug: "predictive-analysis", title: "Predictive Analysis" };
