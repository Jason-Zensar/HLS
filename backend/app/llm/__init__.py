"""Local AI assistant: plain-language explanations, protocol study, RAG chat and an agent over the protocol corpus.

Every answer is generated only from retrieved protocol passages / graph facts that are numbered as sources ([S1], [S2] ...);
the sources, the citations actually used and a grounding check are returned with each answer so a reader can verify it.
"""
