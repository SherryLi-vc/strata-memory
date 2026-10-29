from strata_memory.storage.sqlite_vectors import SqliteVectorStore


def test_sqlite_vector_store_add_query_filter_delete_and_reset(tmp_path):
    store = SqliteVectorStore(tmp_path / "l2_vector")
    store.add(
        documents=["match", "other tenant"],
        metadatas=[{"tenant_id": "a", "user_id": "u"}, {"tenant_id": "b", "user_id": "u"}],
        ids=["a1", "b1"],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
    )

    assert store.db_path.name == "vectors.sqlite3"
    assert store.query([0.9, 0.1], top_k=1)[0]["id"] == "a1"
    filtered = store.query([1.0, 0.0], where={"$and": [{"tenant_id": "a"}, {"user_id": "u"}]})
    assert [item["id"] for item in filtered] == ["a1"]
    assert store.count() == 2
    assert store.existing_ids(["a1", "missing"]) == {"a1"}

    store.delete_by_ids(["a1"])
    assert store.count() == 1
    store.reset()
    assert store.count() == 0
    store.close()
