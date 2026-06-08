"""
验证 P3-Schema Registry
"""
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_schema_registry_imports():
    """db_schema 模块可正常导入"""
    import db_schema
    assert isinstance(db_schema.SCHEMAS, list)
    assert len(db_schema.SCHEMAS) >= 5
    print(f"✅ test_schema_registry_imports PASSED: {len(db_schema.SCHEMAS)} DBs registered")


def test_schema_registry_covers_all_dbs():
    """SCHEMAS 覆盖 6 个核心数据库"""
    import db_schema
    db_names = {db_name for _, db_name, _ in db_schema.SCHEMAS}
    expected = {
        "accounts",
        "user_profiles",
        "feedback",
        "policy_updates",
        "long_term_memory",
        "behavior_tracker",
    }
    missing = expected - db_names
    assert not missing, f"缺失数据库: {missing}"
    print(f"✅ test_schema_registry_covers_all_dbs PASSED: covers {sorted(db_names)}")


def test_init_all_schemas_creates_tables():
    """init_all_schemas 在真实数据目录下创建表"""
    import db_schema
    db_schema.ensure_data_dirs()

    result = db_schema.init_all_schemas()
    # 6 个数据库都被初始化
    assert len(result) == len(db_schema.SCHEMAS), f"应初始化 {len(db_schema.SCHEMAS)} 个 DB,实际 {len(result)}"
    # 每个 DB 至少一张表
    for db_name, tables in result.items():
        assert len(tables) > 0, f"{db_name} 没有任何表"
    print(f"✅ test_init_all_schemas_creates_tables PASSED: {result}")


def test_init_all_schemas_idempotent():
    """重复调用 init_all_schemas 不会抛异常(幂等)"""
    import db_schema
    db_schema.init_all_schemas()
    db_schema.init_all_schemas()
    db_schema.init_all_schemas()
    print("✅ test_init_all_schemas_idempotent PASSED")


def test_get_schema_info_returns_metadata():
    """get_schema_info 返回元信息(供文档/Alembic 参考)"""
    import db_schema
    info = db_schema.get_schema_info()
    assert isinstance(info, list)
    assert len(info) > 0
    for entry in info:
        assert "db" in entry
        assert "db_path" in entry
        assert "tables" in entry
        assert len(entry["tables"]) > 0
        for t in entry["tables"]:
            assert "name" in t
            assert "sql" in t
            assert "CREATE TABLE" in t["sql"]
    print(f"✅ test_get_schema_info_returns_metadata PASSED: {len(info)} DBs documented")


def test_each_table_actually_exists():
    """每张表在数据库中真实存在"""
    import db_schema
    db_schema.init_all_schemas()

    for db_path, db_name, tables in db_schema.SCHEMAS:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing = {row[0] for row in cur.fetchall()}
        for table_name, _ in tables:
            assert table_name in existing, f"{db_name}.{table_name} 缺失"
        conn.close()
    print("✅ test_each_table_actually_exists PASSED")


if __name__ == "__main__":
    test_schema_registry_imports()
    test_schema_registry_covers_all_dbs()
    test_init_all_schemas_creates_tables()
    test_init_all_schemas_idempotent()
    test_get_schema_info_returns_metadata()
    test_each_table_actually_exists()
    print("\n🎉 all schema registry tests passed")
