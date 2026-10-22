// Verification queries for Stage 2.
// Open Neo4j Browser at http://localhost:7474 and paste these one by one.

// 1. Node counts
MATCH (a:Author) RETURN count(a) AS authors;
MATCH (p:Paper) RETURN count(p) AS papers;
MATCH (i:Institution) RETURN count(i) AS institutions;
MATCH (t:Topic) RETURN count(t) AS topics;

// 2. Relationship counts
MATCH ()-[r:WROTE]->() RETURN count(r) AS wrote;
MATCH ()-[r:AFFILIATED_WITH]->() RETURN count(r) AS affiliated_with;
MATCH ()-[r:ABOUT]->() RETURN count(r) AS about;
MATCH ()-[r:CITES]->() RETURN count(r) AS cites;
MATCH ()-[r:CO_AUTHORED]->() RETURN count(r) AS co_authored;

// 3. Structural sanity
MATCH (p:Paper) WHERE NOT (p)<-[:WROTE]-() RETURN count(p) AS papers_without_author;
MATCH (p:Paper) WHERE NOT (p)-[:ABOUT]->() RETURN count(p) AS papers_without_topic;
MATCH (a:Author) WHERE NOT (a)-[:AFFILIATED_WITH]->() RETURN count(a) AS authors_without_institution;
MATCH ()-[r:CO_AUTHORED]->() WHERE r.weight IS NULL RETURN count(r) AS edges_without_weight;

// 4. Core flag (1 = author has at least two papers)
MATCH (a:Author) WHERE a.core = 1 RETURN count(a) AS core_authors;

// 5. Sample: the ten authors with most co-authors
MATCH (a:Author)
RETURN a.name AS author, a.primary_institution AS institution, a.degree AS degree
ORDER BY degree DESC LIMIT 10;

// 6. Sample: a small readable subgraph (good for a screenshot)
MATCH (a:Author)-[r:CO_AUTHORED]-(b:Author)
WHERE a.degree > 100
RETURN a, r, b LIMIT 100;

// 7. GDS
CALL gds.version();
CALL gds.graph.list()
YIELD graphName, nodeCount, relationshipCount
RETURN graphName, nodeCount, relationshipCount;
