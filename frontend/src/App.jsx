import { useEffect, useState } from "react";

import { API_BASE } from "./api";
import FragilityView from "./views/FragilityView";
import NetworkExplorer from "./views/NetworkExplorer";
import RecommenderView from "./views/RecommenderView";
import ReviewersView from "./views/ReviewersView";

/**
 * The four required views. `id` is used in the URL hash (`#/fragility`), which
 * makes every view directly linkable and screenshot-friendly.
 */
const VIEWS = [
  {
    id: "network",
    number: "1",
    label: "Network explorer",
    title: "Network explorer",
    subtitle:
      "The strongest co-authorship ties in the core network, coloured by Louvain community. Click a node for its profile.",
    component: NetworkExplorer,
  },
  {
    id: "fragility",
    number: "2",
    label: "Critical & fragility",
    title: "Critical researchers & fragility",
    subtitle:
      "Who would damage the network most if removed? Rankings, cut vertices and the cascade experiment.",
    component: FragilityView,
  },
  {
    id: "recommender",
    number: "3",
    label: "Silos & recommendations",
    title: "Silos & collaboration recommender",
    subtitle:
      "Where the closed groups are, and which new collaborations the network structure predicts - checked against real 2021+ papers.",
    component: RecommenderView,
  },
  {
    id: "reviewers",
    number: "4",
    label: "Reviewer assignment",
    title: "Reviewer assignment",
    subtitle:
      "Three well-matched reviewers per paper under a workload cap of three, with no conflicts of interest.",
    component: ReviewersView,
  },
];

/** Read the current view from the URL hash, defaulting to the explorer. */
function currentView() {
  const id = window.location.hash.replace(/^#\/?/, "");
  return VIEWS.some((view) => view.id === id) ? id : "network";
}

export default function App() {
  const [viewId, setViewId] = useState(currentView);
  useEffect(() => {
    const onHashChange = () => setViewId(currentView());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const active = VIEWS.find((view) => view.id === viewId) ?? VIEWS[0];
  const ActiveView = active.component;

  return (
    <>
      <header className="hero">
        <div className="hero-inner">
          <p className="eyebrow">Pakistan's Researchers Network</p>
          <h1>Who holds Pakistan's research together?</h1>
          <p className="lede">
            A co-authorship knowledge graph built from real OpenAlex records:
            who collaborates, which groups are isolated, which links are likely
            to form, and how we would assign reviewers without conflicts.
          </p>
          <p className="source">
            OpenAlex (CC0 1.0) - 42,774 authors - 170,700 co-author edges -
            Neo4j 5.26 + Graph Data Science - FastAPI
          </p>
        </div>
      </header>

      <nav className="tabs" aria-label="Views">
        {VIEWS.map((view) => (
          <a
            key={view.id}
            className={`tab ${view.id === viewId ? "active" : ""}`.trim()}
            href={`#/${view.id}`}
            aria-current={view.id === viewId ? "page" : undefined}
          >
            <span className="tab-index">{view.number}</span>
            {view.label}
          </a>
        ))}
      </nav>

      <main className="container">
        <div className="view-head">
          <h2>{active.title}</h2>
          <p className="view-sub">{active.subtitle}</p>
        </div>
        <ActiveView />
      </main>

      <footer>
        <div className="footer-inner">
          <span>
            Data: OpenAlex (CC0 1.0). Analysis: Neo4j 5.26 + GDS, Python.
            Nothing on screen is synthetic.
          </span>
          <span>API: {API_BASE}</span>
        </div>
      </footer>
    </>
  );
}
