// Schema for the Pakistan researchers knowledge graph.
// Run each statement in Neo4j Browser, or let analysis/load_neo4j.py do it.

CREATE CONSTRAINT author_id_unique IF NOT EXISTS
FOR (a:Author) REQUIRE a.author_id IS UNIQUE;

CREATE CONSTRAINT paper_id_unique IF NOT EXISTS
FOR (p:Paper) REQUIRE p.paper_id IS UNIQUE;

CREATE CONSTRAINT institution_id_unique IF NOT EXISTS
FOR (i:Institution) REQUIRE i.institution_id IS UNIQUE;

CREATE CONSTRAINT topic_id_unique IF NOT EXISTS
FOR (t:Topic) REQUIRE t.topic_id IS UNIQUE;

CREATE INDEX author_name IF NOT EXISTS FOR (a:Author) ON (a.name);
CREATE INDEX author_core IF NOT EXISTS FOR (a:Author) ON (a.core);
CREATE INDEX paper_year IF NOT EXISTS FOR (p:Paper) ON (p.year);
CREATE INDEX institution_country IF NOT EXISTS FOR (i:Institution) ON (i.country_code);
