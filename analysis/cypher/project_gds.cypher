// GDS projections used by the analysis stages.
// authorGraphFull: every author and every co-authorship edge.
// authorGraph:     only authors with at least two papers (the core network).

CALL gds.graph.project(
  'authorGraphFull',
  'Author',
  {CO_AUTHORED: {type: 'CO_AUTHORED', orientation: 'UNDIRECTED'}},
  {nodeProperties: ['core', 'degree', 'strength'], relationshipProperties: ['weight']}
);

CALL gds.graph.filter('authorGraph', 'authorGraphFull', 'n.core = 1 AND n.degree > 0', '*');

// Check the projections
CALL gds.graph.list()
YIELD graphName, nodeCount, relationshipCount
RETURN graphName, nodeCount, relationshipCount;

// Smoke test: PageRank on the core graph
CALL gds.pageRank.stream('authorGraph', {maxIterations: 20, dampingFactor: 0.85})
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).name AS name, score
ORDER BY score DESC LIMIT 10;
