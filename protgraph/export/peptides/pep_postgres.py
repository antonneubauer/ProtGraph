import psycopg2

from protgraph.export.peptides.abstract_peptide_exporter import \
    APeptideExporter


class PepPostgres(APeptideExporter):
    """
    A PostGreSQL - Exporter to export PEPTIDES
    into the peptides table

    Those tables will contain all output generated by
    each of the processes. Keep in mind that this table can
    be extremely large, depending on the parmeters set in this tool.

    NOTE: Maybe even exceeding trillion of results for one protein!
    """

    @property
    def skip_x(self) -> bool:
        return self.get_postgres_skip_x

    @property
    def peptide_min_length(self) -> int:
        return self.get_peptide_min_length

    @property
    def max_miscleavages(self) -> int:
        return self.get_miscleavages

    @property
    def use_igraph(self) -> bool:
        return self.get_use_igraph

    @property
    def peptide_max_length(self) -> int:
        return self.get_peptide_length

    @property
    def batch_size(self) -> int:
        return self.get_batch_size

    def start_up(self, **kwargs):
        # Here we generate a connection to postgres
        # and generate the corresponding tables

        # Connection and other parameters
        self.host = kwargs["pep_postgres_host"]  # Host
        self.port = kwargs["pep_postgres_port"]  # Port
        self.user = kwargs["pep_postgres_user"]  # User
        self.password = kwargs["pep_postgres_password"]  # Password
        self.database = kwargs["pep_postgres_database"]  # Database
        self.postgres_no_duplicates = kwargs["pep_postgres_no_duplicates"]

        # Traversal parameters:
        self.get_peptide_length = kwargs["pep_postgres_hops"]  # Number of hops. E.G. 2: s -> h_1 -> h_2 -> e
        self.get_miscleavages = kwargs["pep_postgres_miscleavages"]  # A filter criterion how many miscleavages?
        self.get_peptide_min_length = kwargs["pep_postgres_min_pep_length"]  # Peptide minimum length
        self.get_postgres_skip_x = kwargs["pep_postgres_skip_x"]
        self.get_use_igraph = kwargs["pep_postgres_use_igraph"]
        self.get_batch_size = kwargs["pep_postgres_batch_size"]

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
            raise Exception("Could not establish a connection to Postgres (Peptides).", e)

        # Create tables if they not exist
        try:
            self._create_tables(**kwargs)
        except Exception as e:
            raise Exception("Could not create tables in Postgres (Peptides).", e)

    def _create_tables(self, **kwargs):
        """ Create the accessions and peptides and peptides_meta tables """
        try:
            # create accessions, so that we only save numbers in the large table!
            cur = self.conn.cursor()
            cur.execute("""
                create table if not exists accessions (
                    id SERIAl PRIMARY KEY,
                    accession VARCHAR(15) NOT NULL
                );""")
        except Exception as e:
            print("Error createing accessions table. Continuing... (Reason: {})".format(str(e)))
        finally:
            self.conn.commit()
            cur.close()

        try:
            # Create the large peptides table containing most information
            cur = self.conn.cursor()
            cur.execute("""
            CREATE TABLE  if not exists peptides (
                id {0},
                weight {1} NOT NULL,
                a_count SMALLINT NOT NULL,
                b_count SMALLINT NOT NULL,
                c_count SMALLINT NOT NULL,
                d_count SMALLINT NOT NULL,
                e_count SMALLINT NOT NULL,
                f_count SMALLINT NOT NULL,
                g_count SMALLINT NOT NULL,
                h_count SMALLINT NOT NULL,
                i_count SMALLINT NOT NULL,
                j_count SMALLINT NOT NULL,
                k_count SMALLINT NOT NULL,
                l_count SMALLINT NOT NULL,
                m_count SMALLINT NOT NULL,
                n_count SMALLINT NOT NULL,
                o_count SMALLINT NOT NULL,
                p_count SMALLINT NOT NULL,
                q_count SMALLINT NOT NULL,
                r_count SMALLINT NOT NULL,
                s_count SMALLINT NOT NULL,
                t_count SMALLINT NOT NULL,
                u_count SMALLINT NOT NULL,
                v_count SMALLINT NOT NULL,
                w_count SMALLINT NOT NULL,
                x_count SMALLINT NOT NULL,  -- NOT SKIPPED
                y_count SMALLINT NOT NULL,
                z_count SMALLINT NOT NULL,
                n_terminus character(1) NOT NULL,
                c_terminus character(1) NOT NULL,
                PRIMARY KEY (id));""".format(
                "BIT(452)" if self.postgres_no_duplicates else "BIGSERIAL",
                "BIGINT" if kwargs["mass_dict_type"] is int else "DOUBLE PRECISION"
                ))
        except Exception as e:
            print("Error createing peptides table. Continuing... (Reason: {})".format(str(e)))
        finally:
            self.conn.commit()
            cur.close()
            self.peptides_keys = [
                "weight",
                "a_count", "b_count", "c_count", "d_count", "e_count", "f_count", "g_count", "h_count",
                "i_count", "j_count", "k_count", "l_count", "m_count", "n_count", "o_count", "p_count",
                "q_count", "r_count", "s_count", "t_count", "u_count", "v_count", "w_count", "x_count",
                "y_count", "z_count", "n_terminus", "c_terminus"
            ]
            if self.postgres_no_duplicates:
                self.peptides_keys = ["id"] + self.peptides_keys

        try:
            # Create the peptides meta information (can also be extremely large), larger than the peptides tables
            cur = self.conn.cursor()
            cur.execute("""
            CREATE TABLE  if not exists peptides_meta (
                id BIGSERIAL,
                peptides_id {0},
                accession_id INT,
                path INT[] NOT NULL,
                miscleavages INT NOT NULL,
                PRIMARY KEY (id)
            );""".format("BIT(452)" if self.postgres_no_duplicates else "BIGINT"))
            # References to peptide and accession removed for performance reasons
        except Exception as e:
            print("Error createing peptides_meta table. Continuing... (Reason: {})".format(str(e)))
        finally:
            self.conn.commit()
            cur.close()
            self.peptides_meta_keys = [
                "peptides_id",
                "accession_id",
                "path",
                "miscleavages"
            ]

        # Set statements for inserting or selecting
        self.statement_accession = "INSERT INTO accessions(accession) VALUES (%s) RETURNING id;"
        self.statement_peptides_inner_values = "(" + ",".join(["%s"]*len(self.peptides_keys)) + ")"
        self.statement_peptides_meta_inner_values = "(" + ",".join(["%s"]*len(self.peptides_meta_keys)) + ")"

    def export(self, prot_graph, queue):
        # First insert accession into accession table and retrieve its id:
        # since we only do this per protein!
        with self.conn:
            accession = prot_graph.vs[0]["accession"]
            self.cursor.execute(
                self.statement_accession,
                (accession,)
            )
            self.accession_id = self.cursor.fetchone()[0]

        # Then we continue with the export function
        super().export(prot_graph, queue)

        # and commit everything in the conenction for a protein
        self.conn.commit()

    def export_peptides(self, prot_graph, l_path_nodes, l_path_edges, l_peptide, l_miscleavages, _):
        # Get the weight
        if "mono_weight" in prot_graph.es[l_path_edges[0][0]].attributes():
            l_weight = [sum(prot_graph.es[x]["mono_weight"]) for x in l_path_edges]
        else:
            l_weight = [-1]*len(l_path_nodes)

        # Set the output tuple list
        l_peptides_tup = [
            (
                weight,  # Counts of Aminoacids
                peptide.count("A"), peptide.count("B"), peptide.count("C"), peptide.count("D"), peptide.count("E"),
                peptide.count("F"), peptide.count("G"), peptide.count("H"), peptide.count("I"), peptide.count("J"),
                peptide.count("K"), peptide.count("L"), peptide.count("M"), peptide.count("N"), peptide.count("O"),
                peptide.count("P"), peptide.count("Q"), peptide.count("R"), peptide.count("S"), peptide.count("T"),
                peptide.count("U"), peptide.count("V"), peptide.count("W"), peptide.count("X"), peptide.count("Y"),
                peptide.count("Z"),  # N and C Terminus
                peptide[0], peptide[-1]
            )
            for peptide, weight in zip(l_peptide, l_weight)
        ]

        # Insert new entry into database:
        if self.postgres_no_duplicates:
            self.conn.commit()  # Commit changes, we may need to reapply peptides (when deadlocks are caused)
            l_peptides_id = self._export_peptide_no_duplicate(l_peptides_tup, l_path_nodes, l_miscleavages)
        else:
            l_peptides_id = self._export_peptide_simple_insert(l_peptides_tup, l_path_nodes, l_miscleavages)

        # Bulk insert meta data information of peptides (ALWAYS)
        l_peptides_meta_tup = [
            (
                peptides_id,
                self.accession_id,
                path_nodes,
                miscleavages
            )
            for peptides_id, path_nodes, miscleavages in zip(l_peptides_id, l_path_nodes, l_miscleavages)
        ]
        # Bulk insert statement and execute
        stmt = "INSERT INTO peptides_meta (" \
            + ",".join(self.peptides_meta_keys) \
            + ") VALUES " \
            + ",".join([self.statement_peptides_meta_inner_values]*len(l_peptides_id))
        self.cursor.execute(stmt, [y for x in l_peptides_meta_tup for y in x])

    def _export_peptide_simple_insert(self, l_peptides_tup, l_path_nodes, l_miscleavages):
        """ Simply export them by using simple bulk insert statements """
        stmt = "INSERT INTO peptides (" \
            + ",".join(self.peptides_keys) \
            + ") VALUES " \
            + ",".join([self.statement_peptides_inner_values]*len(l_peptides_tup)) \
            + " returning id"
        self.cursor.execute(stmt, [y for x in l_peptides_tup for y in x])
        peptides_id_fetched = self.cursor.fetchall()
        return [x[0] for x in peptides_id_fetched]

    def _export_peptide_no_duplicate(self, l_peptides_tup, l_path_nodes, l_miscleavages):
        """ Export peptides ONLY if it is not already inserted into the peptides table """
        # Map peptides to 452 many bits (as id)
        pep_ids = [
            "".join(
                # Here we use for the aa-counts 17 bits (each)
                # followed by 5 bits for the n and c terminus (ascii_code - 65)
                # The weight is disregarded, since it is composed by the aa counts
                [format(i, 'b').zfill(17) for i in x[1:-2]] \
                + [format(ord(i) - 65, 'b').zfill(5) for i in x[-2:]]
            )
            for x in l_peptides_tup
        ]

        # Bulk insert into the peptides table
        ins_stmt = " INSERT INTO peptides (" \
            + ",".join(self.peptides_keys) \
            + ") VALUES " \
            + ",".join([self.statement_peptides_inner_values]*len(l_peptides_tup)) \
            + " ON CONFLICT DO NOTHING"
        self._execute_export_no_duplicates(
            ins_stmt,
            [y for a, b in zip(l_peptides_tup, pep_ids) for y in [b] + list(a)]
        )

        # No need to fetch ids, since we generate them ourselves!
        return pep_ids

    def _execute_export_no_duplicates(self, statement, entries):
        # Execute statement. Retry if failed.
        try:
            self.cursor.execute(statement, entries)
        except Exception:
            self.conn.rollback()
            self._execute_export_no_duplicates(statement, entries)

    def tear_down(self):
        # Close the connection to postgres
        try:
            self.cursor.close()  # Close cursor
            self.conn.close()  # Close connection
        except Exception as e:
            print("Connection to PostgreSQL  could not be closed. (Reason: {})".format(str(e)))