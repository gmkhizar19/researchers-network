import { useMemo, useState } from "react";

import LineChart from "../components/LineChart";
import {
  Badge,
  ErrorState,
  Explain,
  Loading,
  Section,
  StatCard,
} from "../components/Ui";
import { fmtInt, fmtPctRaw, fmtScore } from "../format";
import { useApi } from "../useApi";

const SORTS = [
  { value: "betweenness", label: "Betweenness" },
  { value: "pagerank", label: "PageRank" },
  { value: "degree", label: "Degree" },
  { value: "kcore", label: "k-core" },
];

/**
 * View 2 - Problem 1: who is critical, and what happens when they are removed.
 */
export default function FragilityView() {
  const [sort, setSort] = useState("betweenness");
  const fragility = useApi("/api/fragility");
  const critical = useApi(`/api/critical?limit=25&sort=${sort}`);

  const series = useMemo(() => {
    const curves = fragility.data?.cascade?.curves;
    const nodes = fragility.data?.graph?.nodes;
    if (!curves || !nodes) {
      return [];
    }

    const points = (curve) =>
      curve.map((point) => ({
        x: (point.removed / nodes) * 100,
        y: point.lcc_fraction * 100,
      }));

    // The random baseline is 20 replicates: average them point by point so one
    // line is readable (the spread is about +/-0.13 percentage points).
    const randomRuns = curves.random_curves;
    const randomMean = randomRuns[0].map((point, index) => ({
      x: (point.removed / nodes) * 100,
      y:
        (randomRuns.reduce((sum, run) => sum + run[index].lcc_fraction, 0) /
          randomRuns.length) *
        100,
    }));

    return [
      {
        name: "Betweenness",
        color: "#b91c1c",
        points: points(curves.betweenness),
      },
      { name: "PageRank", color: "#b45309", points: points(curves.pagerank) },
      { name: "Degree", color: "#0f766e", points: points(curves.degree) },
      {
        name: "Random (20 runs)",
        color: "#64748b",
        points: randomMean,
        dashed: true,
      },
    ];
  }, [fragility.data]);

  if (fragility.loading) {
    return <Loading label="Loading Problem 1 results..." />;
  }
  if (fragility.error) {
    return <ErrorState message={fragility.error} />;
  }

  const result = fragility.data;
  const last = (seriesName) => {
    const line = series.find((item) => item.name === seriesName);
    return line ? line.points[line.points.length - 1].y : null;
  };
  const removedPercent = result.cascade.max_fraction * 100;

  return (
    <>
      <Explain>
        Betweenness counts how many shortest paths pass through an author, so a
        high score means the author bridges otherwise separate groups. Removing
        the top {removedPercent}% by betweenness shrinks the largest connected
        component to {fmtPctRaw(last("Betweenness"))}, versus{" "}
        {fmtPctRaw(last("Random (20 runs)"))} for random removal. The network has{" "}
        {fmtInt(result.articulation.count)} cut vertices and{" "}
        {fmtInt(result.bridges.count)} bridges, yet a dense core keeps it hard to
        split: there are {fmtInt(result.maxflow.max_flow)} node-disjoint paths
        between {result.maxflow.source} and {result.maxflow.target}.
      </Explain>

      <div className="grid grid-4">
        <StatCard
          label="Articulation points"
          value={fmtInt(result.articulation.count)}
          hint={`${fmtPctRaw(result.articulation.pct_of_nodes)} of core authors`}
          tone="warn"
        />
        <StatCard
          label="Bridges"
          value={fmtInt(result.bridges.count)}
          hint="edges whose removal disconnects"
        />
        <StatCard
          label="Maximum k-core"
          value={fmtInt(result.kcore.max)}
          hint="densest nested group"
          tone="accent"
        />
        <StatCard
          label="Max node-disjoint paths"
          value={fmtInt(result.maxflow.max_flow)}
          hint={`${result.maxflow.source} <-> ${result.maxflow.target}`}
        />
      </div>

      <Section
        title={`Cascade: largest component after removing the top ${removedPercent}%`}
        hint="Core network, 14,574 authors. Targeted removal vs 20 random replicates."
      >
        {series.length ? (
          <LineChart
            series={series}
            xLabel="Share of authors removed (%)"
            yLabel="Largest connected component (%)"
          />
        ) : (
          <p className="empty">No cascade curves found.</p>
        )}
        <div className="callout">
          After {fmtInt(result.cascade.curves.betweenness.at(-1).removed)}{" "}
          authors removed ({removedPercent}%): betweenness{" "}
          {fmtPctRaw(last("Betweenness"))}, PageRank{" "}
          {fmtPctRaw(last("PageRank"))}, degree {fmtPctRaw(last("Degree"))},
          random {fmtPctRaw(last("Random (20 runs)"))}. Targeted removal is
          consistently worse, but the dense core prevents a collapse.
        </div>
      </Section>

      <Section
        title="Critical researchers"
        hint={`Top ${fmtInt(
          critical.data?.total_available ?? 0,
        )} authors by betweenness (exported by Stage 3), re-sorted by ${sort}.`}
        actions={
          <label className="field">
            Rank by
            <select
              value={sort}
              onChange={(event) => setSort(event.target.value)}
            >
              {SORTS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        }
      >
        {critical.loading ? (
          <Loading label="Loading ranking..." />
        ) : critical.error ? (
          <ErrorState message={critical.error} />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Author</th>
                  <th>Institution</th>
                  <th>Betweenness</th>
                  <th>PageRank</th>
                  <th>Degree</th>
                  <th>k-core</th>
                  <th>Role</th>
                </tr>
              </thead>
              <tbody>
                {critical.data.items.map((author, index) => (
                  <tr key={author.author_id}>
                    <td>{index + 1}</td>
                    <td>
                      <a
                        href={`https://openalex.org/authors/${author.author_id}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {author.name}
                      </a>
                    </td>
                    <td>{author.institution || "-"}</td>
                    <td>{fmtScore(author.betweenness, 0)}</td>
                    <td>{fmtScore(author.pagerank, 3)}</td>
                    <td>{fmtInt(author.degree)}</td>
                    <td>{fmtInt(author.kcore)}</td>
                    <td>
                      {author.is_articulation ? (
                        <Badge tone="warn">cut vertex</Badge>
                      ) : (
                        <span className="note">-</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <p className="note" style={{ marginTop: 14 }}>
        Mean shortest path in the core network:{" "}
        {fmtScore(result.distances.sampled_mean_distance_before, 2)} hops (BFS
        from {fmtInt(result.distances.bfs_sources)} sampled sources). Removing 50
        authors by betweenness leaves the LCC at{" "}
        {fmtPctRaw(result.damage_summary.removed_50_by_betweenness * 100, 2)}{" "}
        versus{" "}
        {fmtPctRaw(result.damage_summary.random_mean_after_50 * 100, 2)} for
        random removal.
      </p>
    </>
  );
}
