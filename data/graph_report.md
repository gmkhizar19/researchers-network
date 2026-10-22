# Graph construction report

Generated: 2026-10-21T09:41:29+00:00

## Projection

- Bipartite `Author -[WROTE]-> Paper` edges are projected into an undirected
  author-author graph: every pair of authors on the same paper is one collaboration.
- Edge `weight` = number of shared papers; `first_year` / `last_year` bound the
  collaboration; `papers` lists up to 20 example paper ids.
- Papers with more than 30 authors are skipped
  (9 papers, avoiding
  19998 clique edges). These are consortium papers,
  not personal collaborations.

## Numbers

| Measure | Value |
|---|---:|
| Authors (all) | 42774 |
| Authors with at least one co-author | 41247 |
| Authors with no collaboration (isolates) | 1527 |
| Papers in the cleaned dataset | 26188 |
| Co-authorship edges | 170700 |
| Sum of edge weights (collaboration instances) | 228485 |
| Connected components (collaboration graph) | 2148 |
| Largest component (nodes) | 32879 |
| **LCC % of collaborating authors** | **79.7%** |
| LCC % of all authors (isolates included) | 76.9% |
| Core graph (authors with 2+ papers): nodes | 14574 |
| Core graph: edges | 81793 |
| Core graph: LCC % | 92.6% |

The **core analysis network** (`author_nodes_core.csv`, `author_edges_core.csv`,
`graphml/author_graph_core.graphml`) keeps authors with at least two papers. This
removes one-off authors, who cannot have a recurring collaboration pattern. It is
the network used by the problem analyses; the full network above is kept for
transparency and for the Neo4j knowledge graph.

Mean degree: 8.28 · median: 5 · max: 324.

## Top 10 authors by degree

| # | Author | Primary institution | Degree | Strength (shared papers) |
|---:|---|---|---:|---:|
| 1 | Imran Ashraf | Yeungnam University | 324 | 843 |
| 2 | Muhammad Attique Khan | HITEC University | 270 | 518 |
| 3 | Yazeed Yasin Ghadi | Al Ain University | 256 | 492 |
| 4 | Tanzila Saba | Prince Sultan University | 250 | 592 |
| 5 | Ali Kashif Bashir | Manchester Metropolitan University | 239 | 359 |
| 6 | Shah Nazir | University of Swabi | 228 | 368 |
| 7 | Amjad Ur Rehman | Prince Sultan University | 219 | 541 |
| 8 | Adnan Akhunzada | COMSATS University Islamabad | 217 | 359 |
| 9 | Muhammad Asif Zahoor Raja | National Yunlin University of Science and Technology | 215 | 667 |
| 10 | Usman Tariq | Prince Sattam Bin Abdulaziz University | 209 | 312 |
