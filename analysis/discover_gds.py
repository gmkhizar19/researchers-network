"""Show the exact signature of a GDS procedure."""

from analysis.common.neo4j_client import get_driver, run

driver = get_driver()
rows = run(
    driver,
    "SHOW PROCEDURES YIELD name, signature "
    "WHERE name IN ['gds.louvain.stream', 'gds.louvain.write', "
    "'gds.nodeSimilarity.stream', 'gds.nodeSimilarity.write', "
    "'gds.graph.project.cypher', 'gds.graph.project', 'gds.modularity.stream'] "
    "RETURN name, signature",
)
for row in rows:
    print(row["name"])
    print(row["signature"])
    print()
