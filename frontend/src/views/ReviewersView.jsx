import { useState } from "react";

import {
  Badge,
  ErrorState,
  Explain,
  Loading,
  Section,
  StatCard,
} from "../components/Ui";
import { fmtInt, fmtPct, fmtScore } from "../format";
import { useApi } from "../useApi";

const PAGE_SIZE = 15;

/**
 * View 4 - Problem 3: assignments, constraints and the comparison with the
 * Hungarian and random baselines.
 */
export default function ReviewersView() {
  const metrics = useApi("/api/reviewers/metrics");
  const [paperInput, setPaperInput] = useState("");
  const [appliedPaper, setAppliedPaper] = useState("");
  const [offset, setOffset] = useState(0);

  const query =
    `/api/reviewers/assignments?limit=${PAGE_SIZE}&offset=${offset}` +
    (appliedPaper ? `&paper_id=${encodeURIComponent(appliedPaper)}` : "");
  const assignments = useApi(query);

  if (metrics.loading) {
    return <Loading label="Loading Problem 3 results..." />;
  }
  if (metrics.error) {
    return <ErrorState message={metrics.error} />;
  }

  const data = metrics.data;
  const flow = data.min_cost_flow;
  const hungarian = data.hungarian_uncapacitated;
  const random = data.random_baseline;

  const rows = [
    {
      method: "Min-cost flow (capacity 3)",
      metrics: flow.metrics,
      coi: flow.verification.conflict_violations,
      capacityViolations: flow.verification.capacity_violations,
    },
    {
      method: "Hungarian (1 per paper)",
      metrics: hungarian.metrics,
      coi: hungarian.verification.conflict_violations,
      capacityViolations: hungarian.verification.capacity_violations,
    },
    {
      method: "Random (100 runs)",
      metrics: {
        coverage: random.coverage_mean,
        mean_score: random.mean_score_mean,
        mean_top_score_per_paper: random.mean_top_score_mean,
        loads: { max: data.scope.reviewer_capacity },
      },
      coi: 0,
      capacityViolations: random.capacity_violations,
    },
  ];

  return (
    <>
      <Explain>
        Each paper needs three reviewers, each reviewer can handle at most
        three papers, and a reviewer is excluded if they are an author, ever
        co-authored with one, are within two co-authorship hops, or share the
        primary institution. Min-cost flow maximises total relevance under both
        constraints:{" "}
        {fmtPct(flow.metrics.coverage)} coverage, mean score{" "}
        {fmtScore(flow.metrics.mean_score)}, zero conflicts of interest, and a
        maximum load of {flow.metrics.loads.max}. Random eligible reviewers score
        only {fmtScore(random.mean_score_mean)}, so the matching is{" "}
        {fmtScore(data.comparison.flow_vs_random_score_lift, 1)}x better.
      </Explain>

      <div className="grid grid-3" style={{ marginBottom: 6 }}>
        <Badge tone="ok">
          {fmtInt(flow.verification.conflict_violations)} COI violations /{" "}
          {fmtInt(flow.metrics.assignments)} assignments
        </Badge>
        <Badge tone="ok">
          Capacity {data.scope.reviewer_capacity} respected (max load{" "}
          {flow.metrics.loads.max})
        </Badge>
        <Badge tone="info">
          {data.scope.reviewers_per_paper} reviewers per paper
        </Badge>
      </div>

      <div className="grid grid-4" style={{ marginTop: 10 }}>
        <StatCard
          label="Coverage"
          value={fmtPct(flow.metrics.coverage)}
          hint={`${fmtInt(flow.metrics.papers_fully_assigned)} of ${fmtInt(
            data.scope.papers_sampled,
          )} papers`}
          tone="accent"
        />
        <StatCard
          label="Mean relevance"
          value={fmtScore(flow.metrics.mean_score)}
          hint="all 3,600 assignments"
        />
        <StatCard
          label="Top reviewer per paper"
          value={fmtScore(flow.metrics.mean_top_score_per_paper)}
          hint="best of the three"
        />
        <StatCard
          label="Random baseline"
          value={fmtScore(random.mean_score_mean)}
          hint={`${fmtScore(data.comparison.flow_vs_random_score_lift, 1)}x lower`}
          tone="warn"
        />
      </div>

      <Section
        title="Method comparison"
        hint="Same papers and same eligible reviewers for all three methods."
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Method</th>
                <th>Coverage</th>
                <th>Mean score</th>
                <th>Top choice / paper</th>
                <th>Max load</th>
                <th>COI</th>
                <th>Capacity violations</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.method}>
                  <td>{row.method}</td>
                  <td>{fmtPct(row.metrics.coverage)}</td>
                  <td>{fmtScore(row.metrics.mean_score)}</td>
                  <td>{fmtScore(row.metrics.mean_top_score_per_paper)}</td>
                  <td>{row.metrics.loads.max}</td>
                  <td>{fmtInt(row.coi)}</td>
                  <td>{fmtInt(row.capacityViolations)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="note" style={{ marginTop: 8 }}>
          Hungarian looks slightly better on the mean because it gives each paper
          exactly one reviewer (its best); it cannot fill the three-reviewer
          requirement without ignoring capacity. The flow keeps the Hungarian
          first choice in {fmtPct(hungarian.top1_agreement_with_flow)} of papers
          while adding two more valid reviewers. Score ={" "}
          {data.scope.score}.
        </p>
      </Section>

      <Section
        title="Assignments"
        hint={`${fmtInt(data.scope.papers_sampled)} papers, ${fmtInt(
          data.scope.reviewers_per_paper,
        )} reviewers each. Filter by an OpenAlex paper id, e.g. W2163918217.`}
        actions={
          <form
            className="controls"
            style={{ margin: 0 }}
            onSubmit={(event) => {
              event.preventDefault();
              setOffset(0);
              setAppliedPaper(paperInput.trim());
            }}
          >
            <label className="field">
              Paper id
              <input
                value={paperInput}
                onChange={(event) => setPaperInput(event.target.value)}
                placeholder="W2163918217"
                style={{ minWidth: 180 }}
              />
            </label>
            <button className="btn btn-primary" type="submit">
              Filter
            </button>
            <button
              className="btn"
              type="button"
              onClick={() => {
                setPaperInput("");
                setAppliedPaper("");
                setOffset(0);
              }}
            >
              Clear
            </button>
          </form>
        }
      >
        {assignments.loading ? (
          <Loading label="Loading assignments..." />
        ) : assignments.error ? (
          <ErrorState message={assignments.error} />
        ) : assignments.data.total === 0 ? (
          <p className="empty">
            No assignments found for paper id "{appliedPaper}". Check the id or
            clear the filter.
          </p>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Paper</th>
                    <th>Rank</th>
                    <th>Reviewer</th>
                    <th>Institution</th>
                    <th>Relevance</th>
                  </tr>
                </thead>
                <tbody>
                  {assignments.data.items.map((row) => (
                    <tr
                      key={`${row.paper_id}-${row.reviewer_id}-${row.reviewer_rank}`}
                    >
                      <td className="paper-cell">
                        <strong>{row.paper_title}</strong>
                        <span>
                          {row.paper_id} - {row.paper_year}
                        </span>
                      </td>
                      <td>
                        <span
                          className={`rank ${row.reviewer_rank === 1 ? "r1" : ""}`.trim()}
                        >
                          {row.reviewer_rank}
                        </span>
                      </td>
                      <td>{row.reviewer_name}</td>
                      <td>{row.reviewer_institution || "-"}</td>
                      <td>{fmtScore(row.combined_score)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pager">
              <span>
                Showing {offset + 1}-
                {offset + assignments.data.returned} of{" "}
                {fmtInt(assignments.data.total)} rows (
                {fmtInt(assignments.data.papers)} papers)
              </span>
              <button
                className="btn"
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Previous
              </button>
              <button
                className="btn"
                type="button"
                disabled={offset + PAGE_SIZE >= assignments.data.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
              </button>
            </div>
          </>
        )}
      </Section>
    </>
  );
}
