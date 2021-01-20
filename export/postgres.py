
import json

import psycopg2
from Bio.SwissProt import FeatureLocation, FeatureTable

from export.abstract_exporter import AExporter


class Postgres(AExporter):
    """
    A PostGreSQL - Exporter to export the tables:
    "nodes" "edges" to a database.

    Those tables will contain all output generated by
    each of the processes (so only 2 tables will be created and processed).

    """

    def start_up(self, **kwargs):
        # Here we generate a connection to postgres
        # and generate the corresponding tables
        self.host = kwargs["postgres_host"]  # Host
        self.port = kwargs["postgres_port"]  # Port
        self.user = kwargs["postgres_user"]  # User
        self.password = kwargs["postgres_password"]  # Password
        self.database = kwargs["postgres_database"]  # Database

        # Initialize connection
        try:
            self.conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                dbname=self.database
            )
            # Set a cursor
            self.cursor = self.conn.cursor()
        except Exception as e:
            raise Exception("Could not establish a connection to Postgres.", e)

        # Create tables if they not exist
        try:
            self._create_tables(**kwargs)
        except Exception as e:
            raise Exception("Could not create tables in Postgres.", e)

    def _create_tables(self, **kwargs):
        """ Create the nodes and edges tables """
        # All currently used keys:
        # Nodes:
        # accession, aminoacid, position, isoform_accession, isoform_position
        # Edges:
        # qualifiers (List), mono_weight, avrg_weight, mono_weight_to_end, avrg_weight_to_end, cleaved
        try:
            # create nodes
            cur = self.conn.cursor()
            cur.execute("""
                create table if not exists nodes (
                    id BIGSERIAL PRIMARY KEY,
                    accession VARCHAR(15) NOT NULL,
                    aminoacid TEXT NOT NULL,
                    position INT,
                    isoform_accession VARCHAR(20),
                    isoform_position INT
                );""")
            self.conn.commit()
            cur.close()
            self.nodes_keys = [
                "accession",
                "aminoacid",
                "position",
                "isoform_accession",
                "isoform_position"
            ]
        except Exception as e:
            print("Error createing nodes table. Continuing... (Reason: {})".format(str(e)))

        try:
            # Create edges
            cur = self.conn.cursor()
            cur.execute("""
                create table if not exists edges (
                    id BIGSERIAL PRIMARY KEY,
                    source BIGINT references nodes(id),
                    target BIGINT references nodes(id),
                    cleaved BOOLEAN,
                    mono_weight {0},
                    mono_weight_to_end {0},
                    avrg_weight {0},
                    avrg_weight_to_end {0},
                    qualifiers JSONB
                );""".format("BIGINT" if kwargs["mass_dict_type"] is int else "DOUBLE PRECISION"))
            self.conn.commit()
            cur.close()
            self.edges_keys = [
                "cleaved",
                "mono_weight",
                "mono_weight_to_end",
                "avrg_weight",
                "avrg_weight_to_end",
                "qualifiers"
            ]
        except Exception as e:
            print("Error createing edges table. Continuing... (Reason: {})".format(str(e)))

    def export(self, prot_graph):
        # Export the protein
        self._export(prot_graph)

    def tear_down(self):
        # Close the connection to postgres
        try:
            self.cursor.close()  # Close cursor
            self.conn.close()  # Close connection
        except Exception as e:
            print("Connection to postgres could not be closed. (Reason: {})".format(str(e)))

    def _export(self, prot_graph):
        # Add nodes and edges to the graph

        # Create table information for graph nodes
        db_nodes = [
            self._get_node_edge_attrs(x.attributes(), self.nodes_keys)
            for x in prot_graph.vs[:]
        ]

        # Create SQL statement to insert all nodes (bulk)
        inner_insert_tuple = ",".join(["%s"]*len(self.nodes_keys))
        insert_tuples = ",".join(["({})".format(inner_insert_tuple)]*len(db_nodes))
        statement = "INSERT INTO nodes({}) VALUES ".format(",".join(self.nodes_keys)) \
                    + insert_tuples + " RETURNING id"

        # Add the values into the statement and execute
        nodes_insert_stmt = self.cursor.mogrify(statement, [y for x in db_nodes for y in x])
        self.cursor.execute(nodes_insert_stmt)

        # Get returning ids of the nodes
        node_ids_bulk = self.cursor.fetchall()

        # Create mapping of postgres-IDs and graph IDs and map the edges to it
        node_ids = [x[0] for x in node_ids_bulk]
        sources = [node_ids[x.source] for x in prot_graph.es[:]]
        targets = [node_ids[x.target] for x in prot_graph.es[:]]

        # Create remaining table information for graph edges
        db_edges = [
            self._get_node_edge_attrs(x.attributes(), self.edges_keys)
            for x in prot_graph.es[:]
        ]

        # Concatenate the complete information
        db_edges_full = [None]*len(db_edges)
        for idx, k in enumerate(zip(sources, targets, db_edges)):
            db_edges_full[idx] = [k[0], k[1]] + k[2]

        # Create SQL statement for adding 1 edge into postgres
        e_inner_insert_tuple = ",".join(["%s"]*len(["source", "target"] + self.edges_keys))
        e_statement = "INSERT INTO edges({}) VALUES ".format(",".join(["source", "target"] + self.edges_keys)) \
                      + "({})".format(e_inner_insert_tuple)

        # Execute this statement on each edge entry
        self.cursor.executemany(e_statement, db_edges_full)

        # Commit conenction
        self.conn.commit()

    def _get_node_edge_attrs(self, node_edge_attrs, key_list):
        """ Get values of nodes/edges, returning None if not present """
        attrs_l = [None]*len(key_list)
        # Return list of node attrs
        for idx, ele in enumerate(key_list):
            if ele in node_edge_attrs:
                if ele == "qualifiers":
                    # Special Case for qualifiers here we do JSON!
                    attrs_l[idx] = json.dumps(self._get_attributes(node_edge_attrs[ele]))
                else:
                    attrs_l[idx] = node_edge_attrs[ele]
        return attrs_l

    def _get_attributes(self, attrs):
        """ Convert qualifiers objects into JSON-Serializable objects """
        if isinstance(attrs, list):
            return [self._get_attributes(x) for x in attrs]
        elif isinstance(attrs, dict):
            return {self._get_attributes(x): self._get_attributes(y) for x, y in attrs.items()}
        elif isinstance(attrs, FeatureLocation):
            return [attrs.nofuzzy_start, attrs.nofuzzy_end]
        elif isinstance(attrs, FeatureTable):
            return {self._get_attributes(x): self._get_attributes(y) for x, y in attrs.__dict__.items()}
        else:
            return attrs
