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

/**
 * View 3 - Problem 2: silos (closed communities) plus the validated
 * collaboration recommender.
 */
export default function RecommenderView() {
  const predictions = useApi("/api/link-predictions");
  const communities = useApi("/api/communities");

  if (predictions.loading || communities.loading) {
    return <Loading label="Loading Problem 2 results..." />;
  }
  if (predictions.error) {
    return <ErrorState message={predictions.error} />;
  }
  if (communities.error) {
    return <ErrorState message={communities.error} />;
  }

  const p2 = predictions.data;
  const benchmark = p2.static_benchmark;
  const split = p2.time_split;
  const silos = communities.data.silos;
  const topCommunities = communities.data.communities_top20.slice(0, 10);

  return (
    <>
      <Explain>
        Adamic-Adar scores a missing pair by summing 1/log(degree) over their
        shared neighbours: a shared rare collaborator is stronger evidence than
        a shared hub. Trained only on pairs whose first shared paper is from 2020
        or earlier, it ranks real 2021+ collaborations with AUC{" "}
        {fmtScore(benchmark.adamic_adar.auc)} - clearly better than chance
        ({fmtScore(benchmark.random_precision_expected)} precision at random).
        Separately, Louvain finds{" "}
        {fmtInt(communities.data.louvain.community_count_gds)} communities; the
        three silos below keep over 90% of their edges inside the group.
      </Explain>

      <div className="grid grid-4">
        <StatCard
          label="Adamic-Adar AUC"
          value={fmtScore(benchmark.adamic_adar.auc)}
          hint="used for the ranking"
          tone="accent"
        />
        <StatCard
          label="Common neighbours AUC"
          value={fmtScore(benchmark.common_neighbours.auc)}
          hint="simpler baseline"
        />
        <StatCard
          label="Jaccard AUC"
          value={fmtScore(benchmark.jaccard.auc)}
          hint="normalised overlap"
        />
        <StatCard
          label="Evaluated positives"
          value={fmtInt(benchmark.positive_pairs)}
          hint={`real 2021+ links among ${fmtInt(
            benchmark.candidate_pairs,
          )} shared-neighbour candidates`}
        />
      </div>

      <Section
        title="How the predictor was tested (no leakage)"
        hint={split.rule}
      >
        <div className="grid grid-4">
          <StatCard
            label="Split year"
            value={split.split_year}
            hint="train on or before, test after"
          />
          <StatCard
            label="Training pairs"
            value={fmtInt(split.train_edges)}
            hint={`${fmtInt(split.train_nodes)} authors in the training graph`}
          />
          <StatCard
            label="New 2021+ collaborations"
            value={fmtInt(split.test_pairs_between_existing_authors)}
            hint={`all new pairs between training authors; ${fmtInt(
              benchmark.positive_pairs,
            )} have a shared neighbour`}
          />
          <StatCard
            label="Candidate coverage"
            value={fmtPct(split.candidate_coverage, 2)}
            hint="random-pair precision, the chance baseline"
          />
        </div>
      </Section>

      <Section
        title="Top predicted collaborations"
        hint="Highest Adamic-Adar pairs that do not yet co-author. Scores are for ranking, not probabilities."
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Researcher pair</th>
                <th>Institutions</th>
                <th>Shared neighbours</th>
                <th>Adamic-Adar</th>
                <th>Jaccard</th>
                <th>Group</th>
              </tr>
            </thead>
            <tbody>
              {p2.recommendations_top20.map((pair) => (
                <tr key={`${pair.rank}-${pair.name_1}-${pair.name_2}`}>
                  <td>{pair.rank}</td>
                  <td>
                    <strong>{pair.name_1}</strong>
                    <br />
                    {pair.name_2}
                  </td>
                  <td>
                    {pair.institution_1 || "-"}
                    <br />
                    {pair.institution_2 || "-"}
                  </td>
                  <td>{fmtInt(pair.shared_neighbours)}</td>
                  <td>{fmtScore(pair.adamic_adar)}</td>
                  <td>{fmtScore(pair.jaccard)}</td>
                  <td>
                    {pair.same_community ? (
                      <Badge tone="ok">same community</Badge>
                    ) : (
                      <Badge tone="info">across groups</Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section
        title="Silos: communities that barely talk to the rest"
        hint={`${
          silos.silos.length
        } detected. Internal edge share = fraction of a group's edges that stay inside it.`}
      >
        <div className="grid grid-3">
          {silos.silos.map((silo) => (
            <div className="silo" key={silo.community_id}>
              <div className="silo-head">
                <h4>Community {silo.community_id}</h4>
                <Badge tone="warn">
                  {fmtPct(silo.internal_edge_share)} internal
                </Badge>
              </div>
              <p>
                {fmtInt(silo.size)} authors. Top institutions:{" "}
                {silo.top_institutions.join(", ")}.
              </p>
            </div>
          ))}
        </div>
        <p className="note" style={{ marginTop: 8 }}>
          Mean participation (share of ties leaving an author's own community):{" "}
          {fmtScore(silos.participation.mean, 3)}; maximum{" "}
          {fmtScore(silos.participation.max, 3)}.
        </p>
      </Section>

      <Section
        title="Largest Louvain communities"
        hint={`Modularity ${fmtScore(
          communities.data.louvain.modularity_gds,
        )} (GDS) / ${fmtScore(
          communities.data.louvain.modularity_python_crosscheck,
        )} (NetworkX cross-check).`}
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Community</th>
                <th>Authors</th>
                <th>Internal edge share</th>
                <th>Top institutions</th>
              </tr>
            </thead>
            <tbody>
              {topCommunities.map((community) => (
                <tr key={community.community_id}>
                  <td>{community.community_id}</td>
                  <td>{fmtInt(community.size)}</td>
                  <td>{fmtPct(community.internal_edge_share)}</td>
                  <td>{community.top_institutions.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <p className="note" style={{ marginTop: 14 }}>
        A recommendation is a structural hypothesis, not proof: Adamic-Adar
        finds pairs with the right neighbourhood, but real collaboration also
        depends on topic fit, funding and opportunity.
      </p>
    </>
  );
}
