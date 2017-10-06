# -*- coding: utf-8 -*-

"""Main module."""

import warnings

import numpy
import pandas

import networkx as nx


def nodes_to_df(G):
    ls = []
    for node in G.nodes(data=True):
        df = {}
        n, data = node
        df['id'] = n
        df['from'] = n
        df['to'] = G.successors(n)
        df['type'] = 'node'
        df.update(data)
        ls.append(df)
    return pandas.DataFrame(ls)


def edges_to_df(G):
    ls = []
    for edge in G.edges(data=True):
        df = {}
        _from, _to, data = edge
        df['from'] = _from
        df['to'] = _to
        df['type'] = 'link'
        df.update(data)
        ls.append(df)
    return pandas.DataFrame(ls)


def sum_edge_attr(G, node, attr, method='edges', filter_key=None,
                  include_filter_flags=None, exclude_filter_flags=None):
    """accumulate attributes for one node_id in network G

    Parameters
    ----------
    G : networkx.Graph or networkx.MultiGraph
        a graph network to sum edge attributes at a given node.
        NOTE: For Directed graphs (DiGraph and MultiDiGraph) the
        'edges' method is equivalent to the 'out_edges' method.
    node : string or int
        the networkx node at which to query edge attributes
    attr : string
        an edge attribute key that maps to an int or float. Strings
        will not throw an error, but string concatenation is not the
        purpose of this function.
    method : string, optional (default='edges')
        a method name to select edges for the summation. Valid
        options include 'edges' (default), 'in_edges' and 'out_edges'.
         NOTE: For Directed graphs (DiGraph and MultiDiGraph) the
        'edges' method is equivalent to the 'out_edges' method.
    filter_key : string, optional (default=None)
        edge attribute key that will be searched by the filter flags kwargs
    include_filter_flags : list, optional (default=None)
    exclude_filter_flags : list, optional (default=None)

    Returns
    -------
    float
        the sum of the values associated with the `attr`

    """

    val = 0
    edges = getattr(G, method)(node, data=True)
    if not edges:
        # warnings.warn('Node {} has no edges to sum'.format(node))
        return val

    for edge in edges:
        _from, _to, data = edge

        if filter_key is not None:  # user intends to filter the edges
            key = data[filter_key]
            if include_filter_flags is not None:
                if any([i in key for i in include_filter_flags]):
                    if exclude_filter_flags is not None:
                        if not any([i in key for i in exclude_filter_flags]):
                            val += data.get(attr, 0)
                    else:
                        val += data.get(attr, 0)

            elif exclude_filter_flags is not None:
                if not any([i in key for i in exclude_filter_flags]):
                    val += data.get(attr, 0)

            else:  # user provided key but no flags, perform summation
                val += data.get(attr, 0)

        else:
            val += data.get(attr, 0)

    return val

def safe_divide(x, y):
    if y == 0:
        return 0
    return x / y

class SwmmNetwork(nx.MultiDiGraph):
    """The SwmmNetwork is initialized by the 'cards' given
    by the SWMM.INP file. This file separates the
    """

    def __init__(self,
                 treated=True,
                 name_col='id',
                 vol_col='volume',
                 load_cols=['load', ],
                 treated_flags=["TR", ],
                 vol_reduced_flags=["INF", "HU"],
                 outfall_flags=['OF'],
                 bmp_performance_mapping={},  # {'flag': fxn(inf_conc)}
                 flag_split_char="-",
                 **kwargs
                 ):
        super().__init__(**kwargs)

        self.name_col = name_col
        self.vol_col = vol_col
        self.load_cols = load_cols
        self.treated_flags = treated_flags
        self.vol_reduced_flags = vol_reduced_flags
        self.outfall_flags = outfall_flags
        self.treated = treated

        self._results = None

    @property
    def results(self):
        if self._results is None:
            self.solve()
        return self._results

    def solve(self):

        vol_col = self.vol_col

        vol_out_col = vol_col + "_out"
        vol_red_col = vol_col + "_reduced"
        vol_tmnt_col = vol_col + "_treated"
        pct_vol_tmnt_col = vol_col + "_pct_treated"
        pct_vol_red_col = vol_col + "_pct_reduced"
        vol_cap_col = vol_col + "_capture"
        pct_vol_cap_col = vol_col + "_pct_capture"

        for node in nx.topological_sort(self):

            # subcatchments have a value in vol_col, all other nodes do not.
            node_vol = self.node[node].get(vol_col, 0)

            # subcatchments have no volume from in_edges, but they do have a node_vol.
            vol_in = sum_edge_attr(
                self, node, vol_col, method='in_edges') + node_vol

            self.node[node][vol_col] = vol_in

            check_vol = self.node[node].get("_ck_" + vol_col, node_vol)
            vol_pct_diff = safe_divide(check_vol - vol_in, check_vol)*100
            vol_pct_diff_col = vol_col + "_pct_diff"
            self.node[node][vol_pct_diff_col] = vol_pct_diff
            # print('{} {:.2f} {:.2f} {:.2f}'.format(node, vol_in, check_vol, vol_pct_diff))

            # some nodes may have no in_edges and are not subcatchments. they cannot
            # have load, so skip load calcs step.
            if vol_in != 0:

                for load_col in self.load_cols:#[i for i in self.load_cols if 'SEDLOAD' in i]:

                    conc_col = load_col + "_conc"

                    load_out_col = load_col + "_out"
                    load_red_col = load_col + '_reduced'
                    pct_load_red_col = load_col + "_pct_reduced"

                    # combine node load from incoming pipes.
                    load_in = sum_edge_attr(
                        self, node, load_col, method='in_edges') + self.node[node].get(load_col, 0)

                    conc_in = safe_divide( load_in , vol_in )

                    # print('{} volume: {:.3f}  load in: {:.3f} conc in: {:.3f}'.format(
                    #     node, vol_in, load_in, conc_in))

                    self.node[node][load_col] = load_in
                    self.node[node][conc_col] = conc_in

                    # TODO: This could be adapted into a 'solve node' function. is
                    # it necessary/cleaner?

                    if load_in > 0:
                        # solve for node effluent loads and volumes
                        for edge in self.out_edges(node, data=True):
                            _from, _to, data = edge

                            if load_col in data:

                                print('\tedge id: {} volume: {:.3f}  load: {:.3f}  pct diff: {:3.2f}'.format(
                                    data[self.name_col], data[vol_col], data[load_col],
                                    ((data[load_col] - (conc_in * data[vol_col])) / data[load_col]) * 100)
                                )
                                warnings.warn(
                                    'Overwriting load data at edge: {} for load {}'.format(data[self.name_col], load_col))

                            data[load_col] = conc_in * data[vol_col]

                            # apply treatment to link via concentration influent vs
                            # effluent relationship
                            if self.treated and any([i in data[self.name_col] for i in self.treated_flags]):
                                eff_conc = ((1 - 0.7) * conc_in)
                                data[load_col] = eff_conc * data[vol_col]

                        if any([i in str(node) for i in self.outfall_flags]):
                            # assume no load reduction or vol reduction
                            load_out = load_in
                            vol_out = vol_in
                            vol_treated = 0
                        else:
                            # don't filter this, we've already adjusted the
                            # loads
                            load_out = sum_edge_attr(
                                self, node, load_col, method='out_edges')
                            vol_out = sum_edge_attr(self, node, vol_col, method='out_edges',
                                                    filter_key=self.name_col, exclude_filter_flags=self.vol_reduced_flags)

                            vol_treated = sum_edge_attr(self, node, vol_col, method='out_edges',
                                                        filter_key=self.name_col, include_filter_flags=self.treated_flags)
                    else:
                        load_out = load_in
                        vol_out = vol_in
                        vol_treated = 0

                    load_reduced = load_in - load_out

                    # assign load attributes
                    self.node[node][load_out_col] = load_out
                    self.node[node][load_red_col] = load_reduced
                    if load_in > 0:
                        self.node[node][pct_load_red_col] = 100 * \
                            (load_reduced / load_in)

                    vol_reduced = vol_in - vol_out

                    # assign vol attributes
                    self.node[node][vol_out_col] = vol_out

                    self.node[node][vol_red_col] = vol_reduced
                    self.node[node][pct_vol_red_col] = 100 * \
                        (vol_reduced / vol_in)

                    self.node[node][vol_tmnt_col] = vol_treated
                    self.node[node][pct_vol_tmnt_col] = 100 * \
                        (vol_treated / vol_in)

                    self.node[node][vol_cap_col] = vol_treated + vol_reduced
                    self.node[node][pct_vol_cap_col] = 100 * \
                        ((vol_treated + vol_reduced) / vol_in)

        self._results = (
            pandas.concat([nodes_to_df(self), edges_to_df(self)])
            .reset_index(drop=True)
            .set_index('id')
            .sort_index()
        )

        return self._results
