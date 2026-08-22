"""Project memory: collecting it, ranking it, and handing it to an agent (ADR 0038/0039).

Everything in here is derived from a fact the platform already stores. There is no
authoring path, and that absence is the property that keeps the layer honest: a derived
copy cannot go stale relative to its original, because it *is* its original, re-read.

Module map, in the order data moves:

    outbox    an activity row becomes "this entity may have changed; go and look"
    worker    claims those hints, one transaction each, and re-reads the entity
    sources   turns an entity into versioned sources (one handler per source type)
    chunking  splits a source into retrievable pieces
    tokenize  the one function that produces lexemes, for both writing and querying
    store     the idempotent upsert, and the tombstone
"""
