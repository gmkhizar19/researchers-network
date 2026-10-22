import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape from "cytoscape";

import { Badge, ErrorState, Explain, Loading, StatCard } from "../components/Ui";
import { fmtInt, fmtScore } from "../format";
import { useApi } from "../useApi";

const LIMITS = [100, 300, 600, 1000];
const MIN_DEGREES = [0, 5, 10, 25, 50];

// Distinct colours for Louvain communities (cycled by community id).
const COMMUNITY_COLORS = [
  "#0f766e",
  "#2563eb",
  "#b45309",
  "#7c3aed",
  "#be123c",
  "#0891b2",
  "#4d7c0f",
  "#c2410c",
  "#4338ca",
  "#0e7490",
  "#a21caf",
  "#15803d",
  "#9a3412",
  "#1d4ed8",
];

function isPkAffiliated(value) {
  return (
    value === true ||
    value === 1 ||
    value === "1" ||
    String(value).toLowerCase() === "true"
  );
}

function colorForCommunity(community) {
  if (community === null || community === undefined) {
    return "#94a3b8";
  }
  return COMMUNITY_COLORS[Math.abs(Number(community)) % COMMUNITY_COLORS.length];
}

/**
 * View 1 - Cytoscape explorer over the degree-ranked induced subgraph.
 *
 * Filters are applied in the browser to the already-loaded top-N subgraph, so
 * they never trigger a new database query (and the note says so).
 */
export default function NetworkExplorer() {
  const [limit, setLimit] = useState(300);
  const [onlyPk, setOnlyPk] = useState(false);
  const [minDegree, setMinDegree] = useState(0);
  const [selectedId, setSelectedId] = useState(null);

  const containerRef = useRef(null);
  const cyRef = useRef(null);

  const { data, error, loading } = useApi(`/api/network?limit=${limit}`);
  const profile = useApi(selectedId ? `/api/authors/${selectedId}` : null);

  const visibleNodes = useMemo(() => {
    if (!data) {
      return [];
    }
    return data.nodes.filter(
      (node) =>
        (!onlyPk || isPkAffiliated(node.pk_affiliated)) &&
        Number(node.degree ?? 0) >= minDegree,
    );
  }, [data, onlyPk, minDegree]);

  const visibleEdges = useMemo(() => {
    if (!data) {
      return [];
    }
    const ids = new Set(visibleNodes.map((node) => node.id));
    return data.edges.filter(
      (edge) => ids.has(edge.source) && ids.has(edge.target),
    );
  }, [data, visibleNodes]);

  // (Re)build the Cytoscape instance whenever the data or a filter changes.
  useEffect(() => {
    if (!data || !containerRef.current) {
      return undefined;
    }
    if (!visibleNodes.length) {
      cyRef.current?.destroy();
      cyRef.current = null;
      return undefined;
    }

    const elements = [
      ...visibleNodes.map((node) => ({
        data: {
          id: node.id,
          name: node.name,
          degree: Number(node.degree ?? 0),
          color: colorForCommunity(node.community),
          // Only label the strongest nodes; 300 labels would be unreadable.
          label: Number(node.degree ?? 0) >= 40 ? node.name : "",
        },
      })),
      ...visibleEdges.map((edge, index) => ({
        data: {
          id: `e${index}`,
          source: edge.source,
          target: edge.target,
          weight: Number(edge.weight ?? 1),
        },
      })),
    ];

    const cy = cytoscape({
      container: containerRef.current,
      elements,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            width: "mapData(degree, 0, 350, 9, 46)",
            height: "mapData(degree, 0, 350, 9, 46)",
            label: "data(label)",
            "font-size": 7,
            color: "#1f2937",
            "text-valign": "bottom",
            "text-margin-y": 2,
            "text-max-width": 80,
            "text-wrap": "ellipsis",
            "border-width": 1.5,
            "border-color": "#ffffff",
          },
        },
        {
          selector: "node.selected",
          style: {
            "border-width": 4,
            "border-color": "#0f172a",
          },
        },
        {
          selector: "edge",
          style: {
            width: "mapData(weight, 1, 80, 0.5, 4)",
            "line-color": "#c9d6df",
            opacity: 0.6,
            "curve-style": "bezier",
          },
        },
      ],
      layout: {
        name: "cose",
        animate: false,
        fit: true,
        padding: 24,
        randomize: true,
        nodeRepulsion: 5000,
        idealEdgeLength: 55,
        edgeElasticity: 100,
        gravity: 0.3,
        numIter: 600,
      },
      minZoom: 0.08,
      maxZoom: 3,
      wheelSensitivity: 0.2,
    });

    cy.on("tap", "node", (event) => setSelectedId(event.target.id()));
    cy.on("tap", (event) => {
      if (event.target === cy) {
        setSelectedId(null);
      }
    });

    cyRef.current = cy;
    return () => {
      cy.destroy();
      if (cyRef.current === cy) {
        cyRef.current = null;
      }
    };
  }, [data, visibleNodes, visibleEdges]);

  // Selecting a different author removes the old highlight.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) {
      return;
    }
    cy.nodes().removeClass("selected");
    if (selectedId) {
      cy.getElementById(selectedId).addClass("selected");
    }
  }, [selectedId]);

  // Open the biggest hub by default, so the detail panel is never empty.
  useEffect(() => {
    if (data?.nodes?.length) {
      setSelectedId(data.nodes[0].id);
    }
  }, [data]);

  if (loading) {
    return <Loading label="Loading the graph from Neo4j..." />;
  }
  if (error) {
    return (
      <ErrorState
        message={error}
        hint="This view needs both the FastAPI server and Neo4j. The other three views only need the result files."
      />
    );
  }

  return (
    <>
      <Explain>
        Each dot is an author and each line is at least one shared paper, drawn
        from the core network of authors with two or more papers. Node size is
        their degree, colour is their Louvain community, and line thickness is
        the number of shared papers. The browser only receives the top authors
        by degree, so this is an induced subgraph - not all 14,574 nodes.
      </Explain>

      <div className="grid grid-4">
        <StatCard
          label="Nodes shown"
          value={fmtInt(visibleNodes.length)}
          hint={`of ${fmtInt(data.node_count)} loaded (top ${fmtInt(limit)} by degree)`}
        />
        <StatCard
          label="Edges shown"
          value={fmtInt(visibleEdges.length)}
          hint="only between the visible nodes"
          tone="accent"
        />
        <StatCard
          label="Network layer"
          value="Core"
          hint={data.layer}
        />
        <StatCard
          label="Filters"
          value={onlyPk ? "PK only" : "All authors"}
          hint={minDegree ? `degree >= ${minDegree}` : "no degree cut-off"}
        />
      </div>

      <div className="controls" style={{ marginTop: 14 }}>
        <label className="field">
          Authors loaded
          <select
            value={limit}
            onChange={(event) => setLimit(Number(event.target.value))}
          >
            {LIMITS.map((value) => (
              <option key={value} value={value}>
                Top {value}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Minimum degree
          <select
            value={minDegree}
            onChange={(event) => setMinDegree(Number(event.target.value))}
          >
            {MIN_DEGREES.map((value) => (
              <option key={value} value={value}>
                {value === 0 ? "Any" : `${value}+ papers`}
              </option>
            ))}
          </select>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={onlyPk}
            onChange={(event) => setOnlyPk(event.target.checked)}
          />
          Pakistani-affiliated only
        </label>
        <button
          type="button"
          className="btn"
          onClick={() => cyRef.current?.fit(undefined, 24)}
        >
          Fit graph
        </button>
      </div>

      <div className="network-layout">
        <div className="graph-card">
          <div className="graph-toolbar">
            <div className="legend">
              <span>
                <span
                  className="legend-dot"
                  style={{ background: "#0f766e" }}
                />
                colour = community
              </span>
              <span>size = degree</span>
              <span>line width = shared papers</span>
            </div>
            <span className="note">Wheel to zoom, drag to pan</span>
          </div>
          <div
            ref={containerRef}
            className="graph"
            data-testid="network-graph"
          />
          {!visibleNodes.length ? (
            <p className="empty">
              No authors match these filters. Raise the limit or lower the
              minimum degree.
            </p>
          ) : null}
        </div>

        <AuthorCard authorId={selectedId} profile={profile} />
      </div>

      <p className="note" style={{ marginTop: 10 }}>
        {data.note}
      </p>
    </>
  );
}

/**
 * Side panel: full profile for the clicked author (live from Neo4j).
 */
function AuthorCard({ authorId, profile }) {
  if (!authorId) {
    return (
      <aside className="detail">
        <h4>Author details</h4>
        <p className="muted">
          Click any node to load that author's institution, centrality scores,
          top collaborators and recent papers.
        </p>
        <p className="note" style={{ marginTop: 14 }}>
          Tip: the largest dots are the most connected authors, such as Imran
          Ashraf (degree 324).
        </p>
      </aside>
    );
  }

  if (profile.loading) {
    return (
      <aside className="detail">
        <Loading label="Loading author profile..." />
      </aside>
    );
  }
  if (profile.error) {
    return (
      <aside className="detail">
        <ErrorState message={profile.error} />
      </aside>
    );
  }
  if (!profile.data) {
    return null;
  }

  const { author, papers_in_dataset, coauthors, top_collaborators, recent_papers } =
    profile.data;
  const topics = String(author.topics ?? "")
    .split(/[;|,]/)
    .map((topic) => topic.trim())
    .filter(Boolean)
    .slice(0, 8);
  const isPk = isPkAffiliated(author.pk_affiliated);

  return (
    <aside className="detail">
      <h4>{author.name}</h4>
      <p className="muted">
        {author.id}
        {author.primary_institution ? ` - ${author.primary_institution}` : ""}
      </p>
      <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
        <Badge tone={isPk ? "ok" : "muted"}>
          {isPk ? "Pakistani-affiliated" : "International"}
        </Badge>
        <Badge tone="info">k-core {author.kcore ?? "-"}</Badge>
        {author.community !== null && author.community !== undefined ? (
          <Badge tone="muted">community {author.community}</Badge>
        ) : null}
      </div>

      <dl className="kv">
        <dt>Papers in dataset</dt>
        <dd>{fmtInt(papers_in_dataset)}</dd>
        <dt>Co-authors</dt>
        <dd>{fmtInt(coauthors)}</dd>
        <dt>Degree / strength</dt>
        <dd>
          {fmtInt(author.degree)} / {fmtInt(author.strength)}
        </dd>
        <dt>PageRank</dt>
        <dd>{fmtScore(author.pagerank, 3)}</dd>
        <dt>Betweenness</dt>
        <dd>{fmtScore(author.betweenness, 0)}</dd>
        <dt>Active years</dt>
        <dd>
          {author.first_year ?? "?"} - {author.last_year ?? "?"}
        </dd>
      </dl>

      {topics.length ? (
        <ul className="chip-list" aria-label="Topics">
          {topics.map((topic) => (
            <li key={topic} className="chip">
              {topic}
            </li>
          ))}
        </ul>
      ) : null}

      <h4 style={{ fontSize: 14, marginTop: 16 }}>Top collaborators</h4>
      {top_collaborators.length ? (
        <table className="mini-table">
          <tbody>
            {top_collaborators.map((person) => (
              <tr key={person.id}>
                <td>{person.name}</td>
                <td style={{ textAlign: "right" }}>
                  {fmtInt(person.weight)} papers
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="note">No collaborators in the dataset.</p>
      )}

      <h4 style={{ fontSize: 14, marginTop: 16 }}>Recent papers</h4>
      {recent_papers.length ? (
        <ul className="note" style={{ paddingLeft: 16, margin: 0 }}>
          {recent_papers.map((paper) => (
            <li key={paper.id} style={{ marginBottom: 6 }}>
              {paper.year} - {paper.title}
              {paper.cited_by_count ? ` (${paper.cited_by_count} citations)` : ""}
            </li>
          ))}
        </ul>
      ) : (
        <p className="note">No papers in the dataset.</p>
      )}

      <p style={{ marginTop: 14 }}>
        <a
          href={`https://openalex.org/authors/${author.id}`}
          target="_blank"
          rel="noreferrer"
        >
          Open this author on OpenAlex
        </a>
      </p>
    </aside>
  );
}
