# Neo4j 5.26 Community with the exact GDS version used by this project.
#
# The official image can install GDS through NEO4J_PLUGINS, but that downloads
# ~63 MB again on every container start. Baking the jar into the image makes a
# cold start fast and reproducible.
FROM neo4j:5.26-community

# The 5.26 image sets server.directories.plugins=/plugins.
ARG GDS_VERSION=2.13.14
ADD https://graphdatascience.ninja/neo4j-graph-data-science-${GDS_VERSION}.jar /plugins/graph-data-science.jar
USER root
RUN chmod 644 /plugins/graph-data-science.jar
USER neo4j
