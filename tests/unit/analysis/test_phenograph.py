"""PhenoGraph: shared-neighbour graph + Leiden (scikit-network, BSD)."""

import numpy as np
from scipy import sparse


def test_scikit_network_leiden_splits_two_cliques():
    from sknetwork.clustering import Leiden

    block = np.ones((5, 5)) - np.eye(5)
    graph = sparse.csr_matrix(np.block([[block, np.zeros((5, 5))], [np.zeros((5, 5)), block]]))
    graph[4, 5] = graph[5, 4] = 0.1  # a weak bridge

    labels = Leiden(random_state=0).fit_predict(graph)
    assert len(set(labels[:5])) == 1 and len(set(labels[5:])) == 1
    assert labels[0] != labels[5]
