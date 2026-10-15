import json
import sqlite3
import zipfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import yaml

from personal_data_hub.core.importer import apply_import, preview
from personal_data_hub.core.schema import MASK, validate_schema
from personal_data_hub.core.store import Conflict, Hub, NotFound


def profile(hub):
    return hub.insert(
        "profile",
        {
            "name": "Alice",
            "email": "alice@example.invalid",
            "phone": "FICTIONAL-PRIVATE",
            "city": "Example City",
        },
    )


def test_builtins_and_masking_every_surface(hub, tmp_path, examples):
    assert len(hub.tables()) == 9
    created = profile(hub)
    row_id = created["row"]["id"]
    assert created["row"]["email"] == MASK
    assert hub.get("profile", row_id)["phone"] == MASK
    assert hub.get("profile", row_id, True)["email"] == "alice@example.invalid"
    assert hub.query("profile")[0]["email"] == MASK
    history = hub.history("profile")[0]
    assert history["after"]["phone"] == MASK
    assert "after_json" not in history
    out = tmp_path / "rows.json"
    hub.export("profile", out)
    assert "FICTIONAL-PRIVATE" not in out.read_text()
    assert MASK in out.read_text()
    hub.export("profile", out, reveal=True)
    assert "FICTIONAL-PRIVATE" in out.read_text()
    plan = preview(hub, examples / "profile.json", "profile")
    assert plan["sample"][0]["email"] == MASK
    with pytest.raises(ValueError, match="requires reveal"):
        hub.query("profile", where="email~alice")
    assert hub.query("profile", where="email~alice", reveal=True)
    assert not hub.query("profile", search="FICTIONAL-PRIVATE")
    assert hub.query("profile", search="FICTIONAL-PRIVATE", reveal=True)


def test_audit_update_revert_insert_delete_and_conflicts(hub):
    original = profile(hub)
    row_id = original["row"]["id"]
    updated = hub.update("profile", row_id, {"city": "Sample City"}, actor="agent:editor")
    assert hub.history("profile")[0]["actor"] == "agent:editor"
    reverted = hub.revert(updated["change_id"], True, "agent:revert")
    assert reverted["row"]["city"] == "Example City"
    assert hub.history("profile")[0]["reverses"] == updated["change_id"]
    with pytest.raises(Conflict, match="already"):
        hub.revert(updated["change_id"], True)
    removed = hub.delete("profile", row_id, True)
    assert not hub.query("profile")
    assert hub.revert(removed["change_id"], True)["row"]["id"] == row_id
    assert hub.get("profile", row_id, True)["email"] == "alice@example.invalid"
    later = hub.update("profile", row_id, {"city": "New City"})
    hub.update("profile", row_id, {"city": "Another City"})
    with pytest.raises(Conflict, match="later"):
        hub.revert(later["change_id"], True)
    with pytest.raises(Conflict, match="changed"):
        hub.update(
            "profile", row_id, {"city": "Stale"}, expected_updated_at=original["row"]["updated_at"]
        )
    insert = hub.insert("projects", {"name": "Throwaway project"})
    assert hub.revert(insert["change_id"], True)["row"] is None
    assert hub.query("projects") == []


def test_confirmation_validation_and_rollback(hub):
    row = profile(hub)["row"]
    for action in [lambda: hub.delete("profile", row["id"]), lambda: hub.revert("missing")]:
        with pytest.raises(ValueError):
            action()
    with pytest.raises(ValueError):
        hub.insert("profile", {"name": "Rollback"}, actor="")
    assert len(hub.query("profile")) == 1
    with pytest.raises(ValueError):
        hub.update("profile", row["id"], {"email": MASK})
    with pytest.raises(ValueError):
        hub.insert("profile", {"name": "Alice", "id": "illegal"})
    with pytest.raises(NotFound):
        hub.get("profile", "missing")
    with pytest.raises(NotFound):
        hub.describe("missing")
    with pytest.raises(sqlite3.IntegrityError):
        hub.insert("profile", {"name": "Alice"})
    assert hub.update("profile", row["id"], {"city": "Example City"})["unchanged"]


@pytest.mark.parametrize(
    "expression",
    [
        "name=Alice; DROP TABLE h_profile",
        "name='Alice' OR 1=1",
        "name=Alice UNION SELECT *",
        "name=Alice -- comment",
        "name) =Alice",
        "id=1;DELETE",
        "unknown=hello",
        "name=Alice AND",
    ],
)
def test_injection_strings_rejected_without_mutation(hub, expression):
    profile(hub)
    with pytest.raises(ValueError):
        hub.query("profile", where=expression)
    assert len(hub.query("profile")) == 1
    assert len(hub.history()) == 1


def test_safe_literal_quotes_fuzzy_and_comparisons(hub):
    profile(hub)
    hub.insert("profile", {"name": "A AND B", "city": "100% exact"})
    assert len(hub.query("profile", "name='A AND B' AND city~'100%'")) == 1
    assert hub.query("profile", "name!=Alice", fields=["name"])[0] == {"name": "A AND B"}
    assert hub.query("profile", "city=null") == []
    assert len(hub.query("profile", "city!=null")) == 2
    assert hub.query("profile", "name='Alice; DROP TABLE h_profile'") == []
    for value in ["0.1", "0.2", "100000000000000000000.01"]:
        hub.insert(
            "income",
            {"date": "2026-01-01", "category": "example", "reference": value, "amount": value},
        )
    rows = hub.query("income", "amount>0.15 AND amount<=0.20", reveal=True)
    assert [row["amount"] for row in rows] == ["0.2"]
    assert hub.query("income", "amount>100000000000000000000.00", reveal=True)[0][
        "amount"
    ].endswith(".01")
    with pytest.raises(ValueError):
        hub.query("income", "amount>not-a-number", reveal=True)


def test_xlsx_pdf_csv_json_previews_and_idempotent_import(hub, examples):
    for filename, table in [("projects.xlsx", "projects"), ("documents.pdf", "documents")]:
        plan = preview(hub, examples / filename, table)
        assert plan["rows_in"] == 2 and not plan["errors"]
        assert hub.query(table) == []
        assert (
            apply_import(hub, examples / filename, table, confirm=True, expected_sha1=plan["sha1"])[
                "inserted"
            ]
            == 2
        )
        result = apply_import(hub, examples / filename, table, confirm=True)
        assert result["inserted"] == result["updated"] == 0
        assert result["skipped"] == 2
    assert apply_import(hub, examples / "projects.csv", "projects", confirm=True)["skipped"] == 2
    assert apply_import(hub, examples / "profile.json", "profile", confirm=True)["inserted"] == 1
    assert hub.query("documents")[0]["reference"] == MASK
    with pytest.raises(ValueError, match="confirmation|confirm"):
        apply_import(hub, examples / "projects.xlsx", "projects")
    with pytest.raises(ValueError, match="changed"):
        apply_import(
            hub, examples / "projects.xlsx", "projects", confirm=True, expected_sha1="old-hash"
        )


def test_mapping_validation_atomicity_and_upsert(hub, tmp_path, examples):
    custom = tmp_path / "custom.csv"
    custom.write_text("Heading,Place\nAlice,First City\n", encoding="utf-8")
    mapping = {"Heading": "name", "Place": "city"}
    assert preview(hub, custom, "profile", mapping)["valid_rows"] == 1
    assert apply_import(hub, custom, "profile", mapping, confirm=True)["inserted"] == 1
    custom.write_text("Heading,Place\nAlice,Second City\n", encoding="utf-8")
    assert apply_import(hub, custom, "profile", mapping, confirm=True)["updated"] == 1
    assert hub.query("profile")[0]["city"] == "Second City"
    invalid = tmp_path / "bad.json"
    invalid.write_text(json.dumps([{"name": "Good"}, {"name": ""}]))
    assert len(preview(hub, invalid, "profile")["errors"]) == 1
    with pytest.raises(ValueError):
        apply_import(hub, invalid, "profile", confirm=True)
    assert len(hub.query("profile")) == 1
    with pytest.raises(ValueError):
        preview(hub, custom, "profile", {"Heading": "name", "Place": "name"})


@pytest.mark.parametrize("format", ["json", "csv"])
def test_export_roundtrip_reveal_and_bom(hub, tmp_path, format):
    original = profile(hub)["row"]
    hub.update("profile", original["id"], {"summary": 'Multiline\nnote, with "quotes"'})
    path = tmp_path / f"export.{format}"
    assert hub.export("profile", path, format, reveal=True)["count"] == 1
    if format == "csv":
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    other = Hub(tmp_path / "other")
    assert apply_import(other, path, "profile", confirm=True)["inserted"] == 1
    restored = other.get("profile", original["id"], True)
    assert restored["email"] == "alice@example.invalid"
    assert restored["summary"] == 'Multiline\nnote, with "quotes"'
    with pytest.raises(ValueError):
        hub.export("profile", hub.path)


def test_schema_add_only_and_sensitive_preservation(hub, examples):
    profile(hub)
    source = hub.schema_dir / "profile.yaml"
    schema = yaml.safe_load(source.read_text())
    schema["columns"]["nickname"] = {"type": "text", "default": "Alias"}
    source.write_text(yaml.safe_dump(schema))
    migrated = Hub(hub.data_dir)
    assert migrated.query("profile")[0]["nickname"] == "Alias"
    schema["columns"].pop("city")
    schema["columns"]["email"]["sensitive"] = False
    source.write_text(yaml.safe_dump(schema))
    retained = Hub(hub.data_dir)
    assert "city" in retained.describe("profile")["columns"]
    assert retained.query("profile")[0]["email"] == MASK
    (hub.schema_dir / "reading_list.yaml").write_bytes(
        (examples / "custom_schema.yaml").read_bytes()
    )
    extended = Hub(hub.data_dir)
    assert len(extended.tables()) == 10
    assert (
        extended.insert("reading_list", {"title": "Sample Handbook"})["row"]["status"] == "planned"
    )


@pytest.mark.parametrize("mutation", ["type", "key", "required", "new_required"])
def test_destructive_schema_changes_rejected(hub, mutation):
    profile(hub)
    path = hub.schema_dir / "profile.yaml"
    schema = yaml.safe_load(path.read_text())
    if mutation == "type":
        schema["columns"]["city"]["type"] = "integer"
    elif mutation == "key":
        schema["unique"] = ["city"]
    elif mutation == "required":
        schema["columns"]["city"]["required"] = True
    else:
        schema["columns"]["required_new"] = {"type": "text", "required": True}
    path.write_text(yaml.safe_dump(schema))
    with pytest.raises(ValueError):
        Hub(hub.data_dir)


def test_due_and_online_backup_restore(hub, tmp_path):
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    hub.insert(
        "documents",
        {
            "name": "Example card",
            "reference": "PRIVATE-EXAMPLE",
            "expires_at": (today + timedelta(days=5)).isoformat(),
        },
    )
    hub.insert(
        "important_dates",
        {"name": "Overdue example", "date": (today - timedelta(days=1)).isoformat()},
    )
    hub.insert(
        "important_dates",
        {"name": "Future example", "date": (today + timedelta(days=60)).isoformat()},
    )
    due = hub.due("30d")
    assert [item["days_remaining"] for item in due] == [-1, 5]
    assert due[1]["row"]["reference"] == MASK
    result = hub.backup()
    with zipfile.ZipFile(result["path"]) as archive:
        assert "hub.db" in archive.namelist() and "schemas/profile.yaml" in archive.namelist()
        archive.extractall(tmp_path / "restore")
    restored = Hub(tmp_path / "restore")
    assert len(restored.due()) == 2
    assert len(restored.history()) == 3
    with pytest.raises(ValueError):
        hub.backup(hub.path)


def test_schema_identifier_and_required_validation():
    with pytest.raises(ValueError):
        validate_schema({"table": 'x";drop', "columns": {"name": {"type": "text"}}})
    with pytest.raises(ValueError):
        validate_schema({"table": "example", "columns": {"id": {"type": "text"}}})
