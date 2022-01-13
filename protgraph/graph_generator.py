import igraph

from collections import defaultdict

from protgraph.aa_masses_annotation import annotate_weights
from protgraph.aa_replacer import replace_aa
from protgraph.digestion import digest
from protgraph.export.exporters import Exporters
from protgraph.ft_execution.signal import execute_signal
from protgraph.ft_execution.init_met import execute_init_met
from protgraph.ft_execution.generic import (execute_mutagen, 
                                            execute_conflict, 
                                            execute_variant)
from protgraph.ft_execution.generic_cleaved_peptide import (execute_propeptide,
                                                            execute_peptide)
from protgraph.ft_execution.var_seq import (_get_isoforms_of_entry,
                                            execute_var_seq)
from protgraph.graph_collapse_edges import collapse_parallel_edges
from protgraph.graph_statistics import get_statistics
from protgraph.merge_aminoacids import merge_aminoacids
from protgraph.verify_graphs import verify_graph


def _generate_canonical_graph(sequence: str, acc: str):
    """
    Generates the canonical directed graph from a sequence.
    This simply generates a chain of nodes and edges and sets
    specific attributes for them.
    """
    # Initialization of the directed graph (DiGraph)
    graph = igraph.Graph(directed=True)

    # Initialize the graph with the length of the sequence
    graph.add_vertices(len(sequence) + 2)  # +2 -> adding start and end node here!
    graph.add_edges([(x1, x1 + 1) for x1 in range(len(sequence) + 1)])

    # Add their amino acid to the corresponding nodes
    graph.vs["aminoacid"] = ["__start__", *[x for x in sequence], "__end__"]

    # Add position attributes to nodes as well as from which accesion they originate
    graph.vs["position"] = list(range(len(sequence) + 2))  # Set position of aa on every node!
    graph.vs["accession"] = [acc, *[acc] * len(sequence), acc]  # Set accession on every node!

    return graph


def _sort_entry_features(entry):
    """ This sorts the features according to their type into a dict. """
    sorted_features = defaultdict(list)
    # For each features
    for f in entry.features:
        # Append it to a list to its corresponding key -> type
        sorted_features[f.type].append(f)

    # Return the dictionary
    return sorted_features


def _include_spefic_ft(graph, ft_type, method, sorted_features, ft_dict):
    """ Execute features individually """
    num_of_feature_type = 0 if ft_type in ft_dict else None
    if ft_type in sorted_features and ft_type in ft_dict:
        num_of_feature_type = len(sorted_features[ft_type])
        for f in sorted_features[ft_type]:
            method(graph, f)
    return num_of_feature_type


def _include_ft_information(entry, graph, ft_dict):
    """ Returns num of possible isoforms and others (on the fly) """
    # Sort features of entry according to their type into a dict
    sorted_features = _sort_entry_features(entry)

    # VAR_SEQ (isoforms) need to be executed at once and before all other variations
    # since those can be referenced by others
    num_of_isoforms = 0 if "VAR_SEQ" in ft_dict else None
    if "VAR_SEQ" in sorted_features and "VAR_SEQ" in ft_dict:
        # Get isoform information of entry as a dict
        isoforms, num_of_isoforms = _get_isoforms_of_entry(entry.comments, entry.accessions[0])
        execute_var_seq(isoforms, graph, entry.sequence, sorted_features["VAR_SEQ"], entry.accessions[0])

    # Execute the other features tables, per feature
    num_of_init_m = _include_spefic_ft(graph, "INIT_MET", execute_init_met, sorted_features, ft_dict)
    num_of_signal = _include_spefic_ft(graph, "SIGNAL", execute_signal, sorted_features, ft_dict)
    num_of_variant = _include_spefic_ft(graph, "VARIANT", execute_variant, sorted_features, ft_dict)
    num_of_mutagens = _include_spefic_ft(graph, "MUTAGEN", execute_mutagen, sorted_features, ft_dict)
    num_of_conflicts = _include_spefic_ft(graph, "CONFLICT", execute_conflict, sorted_features, ft_dict)

    # TODO to be tested on UniProt!
    num_of_propeptides = _include_spefic_ft(graph, "PROPEP", execute_propeptide, sorted_features, ft_dict)
    num_of_peptides = _include_spefic_ft(graph, "PEPTIDE", execute_peptide, sorted_features, ft_dict)

    return num_of_isoforms, num_of_init_m, num_of_signal, num_of_variant, num_of_mutagens, num_of_conflicts


def generate_graph_consumer(entry_queue, graph_queue, common_out_queue, proc_id, **kwargs):
    """
    TODO
    describe kwargs and consumer until a graph is generated and digested etc ...
    """
    # Set proc id
    kwargs["proc_id"] = proc_id

    # Set feature_table dict boolean table
    ft_dict = dict()
    if kwargs["feature_table"] is None or len(kwargs["feature_table"]) == 0 or "ALL" in kwargs["feature_table"]:
        ft_dict = dict(PEPTIDE=True, PROPEP=True, VARIANT=True, VAR_SEQ=True, SIGNAL=True, INIT_MET=True, MUTAGEN=True, CONFLICT=True)
    else:
        for i in kwargs["feature_table"]:
            ft_dict[i] = True

    # Initialize the exporters for graphs
    with Exporters(**kwargs) as graph_exporters:

        while True:
            # Get next entry
            entry = entry_queue.get()

            # Stop if entry is None
            if entry is None:
                # --> Stop Condition of Process
                break

            # Beginning of Graph-Generation
            # We also collect interesting information here!

            # Generate canonical graph (initialization of the graph)
            graph = _generate_canonical_graph(entry.sequence, entry.accessions[0])

            # FT parsing and appending of Nodes and Edges into the graph
            # The amount of isoforms, etc.. can be retrieved on the fly
            num_isoforms, num_initm, num_signal, num_variant, num_mutagens, num_conficts =\
                _include_ft_information(entry, graph, ft_dict)

            # Replace Amino Acids based on user defined rules: E.G.: "X -> A,B,C"
            replace_aa(graph, kwargs["replace_aa"])

            # Digest graph with enzyme (unlimited miscleavages)
            num_of_cleavages = digest(graph, kwargs["digestion"])

            # Merge (summarize) graph if wanted
            if not kwargs["no_merge"]:
                merge_aminoacids(graph)

            # Collapse parallel edges in a graph
            if not kwargs["no_collapsing_edges"]:
                collapse_parallel_edges(graph)

            # Annotate weights for edges and nodes (maybe even the smallest weight possible to get to the end node)
            annotate_weights(graph, **kwargs)

            # Calculate statistics on the graph:
            (
                num_nodes, num_edges, num_paths, num_paths_miscleavages, num_paths_hops,
                num_paths_var, num_path_mut, num_path_con
            ) = get_statistics(graph, **kwargs)

            # Verify graphs if wanted:
            if kwargs["verify_graph"]:
                verify_graph(graph)

            # Persist or export graphs with speicified exporters
            graph_exporters.export_graph(graph, common_out_queue)

            # Output statistics we gathered during processing
            if kwargs["no_description"]:
                entry_protein_desc = None
            else:
                entry_protein_desc = entry.description.split(";", 1)[0]
                entry_protein_desc = entry_protein_desc[entry_protein_desc.index("=") + 1:]

            graph_queue.put(
                (
                    entry.accessions[0],  # Protein Accesion
                    entry.entry_name,  # Protein displayed name
                    num_isoforms,  # Number of Isoforms
                    num_initm,  # Number of Init_M (either 0 or 1)
                    num_signal,  # Number of Signal Peptides used (either 0 or 1)
                    num_variant,  # Number of Variants applied to this protein
                    num_mutagens,  # Number of applied mutagens on the graph
                    num_conficts,  # Number of applied conflicts on the graph
                    num_of_cleavages,  # Number of cleavages (marked edges) this protein has
                    num_nodes,  # Number of nodes for the Protein/Peptide Graph
                    num_edges,  # Number of edges for the Protein/Peptide Graph
                    num_paths,  # Possible (non repeating paths) to the end of a graph. (may conatin repeating peptides)
                    num_paths_miscleavages,  # As num_paths, but binned to the number of miscleavages (by list idx, at 0)
                    num_paths_hops,  # As num_paths, only that we bin by hops (E.G. useful for determine DFS or BFS depths)
                    num_paths_var,  # Num paths of feture variant
                    num_path_mut,  # Num paths of feture mutagen
                    num_path_con,  # Num paths of feture conflict
                    entry_protein_desc,  # Description name of the Protein (can be lenghty)
                )
            )
