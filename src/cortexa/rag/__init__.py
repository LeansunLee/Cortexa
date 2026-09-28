"""RAG (Retrieval-Augmented Generation) module.

Components:
- chunker: Document chunking strategies
- embedder: Text embedding generation
- bm25_search: BM25 keyword retrieval
- retriever: Unified retrieval interface (BM25, HyDE, Multi-Query, Ensemble, Parent-Child)
- hyde: Hypothetical Document Embeddings
- multi_query: Multi-Query retrieval with RRF fusion
- contextual_retrieval: Context-enriched chunk embeddings
- parent_child: Parent-Child document retrieval
"""
