import asyncio
import json
import os
import sys
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from personal_data_hub.cli import main
from personal_data_hub.core.schema import MASK
from personal_data_hub.mcp_server import create_server
from personal_data_hub.web.app import create_app


def cli(capsys, tmp_path, *args):
    status = main(["--data-dir", str(tmp_path / "cli"), *args, "--json"])
    output = capsys.readouterr()
    return status, json.loads(output.out)


def test_cli_end_to_end(capsys, tmp_path, examples):
    assert len(cli(capsys, tmp_path, "init")[1]["data"]["tables"]) == 9
    assert len(cli(capsys, tmp_path, "tables")[1]["data"]) == 9
    assert cli(capsys, tmp_path, "schema", "profile")[1]["data"]["unique"] == ["name"]
    plan = cli(capsys, tmp_path, "import", str(examples / "projects.xlsx"), "--table", "projects")[
        1
    ]["data"]
    assert plan["requires_confirmation"]
    assert cli(capsys, tmp_path, "query", "projects")[1]["data"] == []
    assert (
        cli(
            capsys,
            tmp_path,
            "import",
            str(examples / "projects.xlsx"),
            "--table",
            "projects",
            "--yes",
        )[1]["data"]["inserted"]
        == 2
    )
    created = cli(
        capsys,
        tmp_path,
        "add",
        "profile",
        "--data",
        '{"name":"Alice","email":"alice@example.invalid"}',
    )[1]["data"]
    assert created["row"]["email"] == MASK
    row_id = created["row"]["id"]
    updated = cli(
        capsys, tmp_path, "update", "profile", row_id, "--data", '{"city":"Sample City"}'
    )[1]["data"]
    assert cli(capsys, tmp_path, "history", "--table", "profile")[1]["data"][0]["op"] == "update"
    assert (
        cli(capsys, tmp_path, "revert", updated["change_id"], "--yes")[1]["data"]["row"]["city"]
        is None
    )
    assert cli(capsys, tmp_path, "due")[0] == 0
    assert cli(
        capsys,
        tmp_path,
        "export",
        "profile",
        "--format",
        "csv",
        "--out",
        str(tmp_path / "export.csv"),
    )[1]["data"]["masked"]
    assert cli(capsys, tmp_path, "backup")[1]["data"]["bytes"] > 0
    assert cli(capsys, tmp_path, "delete", "profile", row_id)[0] == 2
    assert cli(capsys, tmp_path, "delete", "profile", row_id, "--yes")[0] == 0


@pytest.mark.parametrize(
    "args,status",
    [
        (["query", "unknown"], 3),
        (["query", "profile", "--limit", "0"], 2),
        (["add", "profile", "--data", "not json"], 2),
        (["query", "profile", "--where", "name=Alice OR 1=1"], 2),
        (["unknown"], 2),
        (["import", "/nonexistent/example.csv", "--table", "profile"], 1),
    ],
)
def test_cli_errors(capsys, tmp_path, args, status):
    returned, payload = cli(capsys, tmp_path, *args)
    assert returned == status
    assert not payload["ok"] and payload["error"]["message"]


def test_cli_globals_help_config(capsys, tmp_path, monkeypatch):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"
    assert main(["--help"]) == 0
    assert "Global:" in capsys.readouterr().out
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path / "env"))
    assert main(["tables", "--quiet"]) == 0
    assert capsys.readouterr().out == ""
    assert main(["tables", "--json", "--progress"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["ok"]
    assert "Running" in output.err


def test_rest_crud_docs_export_auth_and_masking(hub):
    client = TestClient(create_app(hub), base_url="http://127.0.0.1")
    assert client.get("/").status_code == 200
    docs = client.get("/docs")
    assert docs.status_code == 200 and "/docs-assets/" in docs.text
    assert "cdn.jsdelivr" not in docs.text
    assert client.get("/docs-assets/swagger-ui-bundle.js").status_code == 200
    assert "/api/rows/{table}" in client.get("/openapi.json").json()["paths"]
    assert len(client.get("/api/tables").json()["data"]) == 9
    assert client.get("/api/schema/profile").json()["data"]["columns"]["email"]["sensitive"]
    response = client.post(
        "/api/rows/profile",
        json={"name": "Alice", "email": "alice@example.invalid"},
        headers={"X-Actor": "agent:api"},
    )
    assert response.status_code == 201
    row = response.json()["data"]["row"]
    assert row["email"] == MASK
    assert client.get(f"/api/rows/profile/{row['id']}").json()["data"]["email"] == MASK
    assert (
        client.get("/api/rows/profile?reveal=true").json()["data"][0]["email"]
        == "alice@example.invalid"
    )
    updated = client.patch(f"/api/rows/profile/{row['id']}", json={"city": "New City"}).json()[
        "data"
    ]
    history = client.get("/api/history?table=profile").json()["data"]
    assert history[0]["after"]["email"] == MASK
    assert history[-1]["actor"] == "agent:api"
    assert "alice@example.invalid" not in client.get("/api/export/profile").text
    assert client.get("/api/export/profile").content.startswith(b"\xef\xbb\xbf")
    assert (
        client.post(f"/api/revert/{updated['change_id']}?confirm=true").json()["data"]["row"][
            "city"
        ]
        is None
    )
    assert client.get("/api/due").status_code == 200
    assert client.delete(f"/api/rows/profile/{row['id']}").status_code == 422
    assert client.delete(f"/api/rows/profile/{row['id']}?confirm=true").status_code == 200
    assert client.get(f"/api/rows/profile/{row['id']}").status_code == 404
    assert client.get("/api/rows/profile?limit=bad").json()["error"]["code"] == "INVALID_ARGUMENT"
    assert (
        client.post(
            "/api/rows/profile",
            json={"name": "Blocked"},
            headers={"Origin": "http://untrusted.invalid"},
        ).status_code
        == 403
    )
    assert client.get("/api/tables", headers={"Host": "untrusted.invalid"}).status_code == 400
    authenticated = TestClient(
        create_app(hub, token="fictional-test-token"), base_url="http://127.0.0.1"
    )
    assert authenticated.get("/api/tables").status_code == 401
    assert (
        authenticated.get(
            "/api/tables", headers={"Authorization": "Bearer fictional-test-token"}
        ).status_code
        == 200
    )


def payload(result):
    return result.structuredContent or json.loads(result.content[0].text)


def test_every_mcp_tool_with_official_client(hub):
    async def scenario():
        async with create_connected_server_and_client_session(
            create_server(hub, "agent:mcp"), read_timeout_seconds=timedelta(seconds=10)
        ) as client:
            await client.initialize()
            assert {t.name for t in (await client.list_tools()).tools} == {
                "list_tables",
                "describe_table",
                "query_rows",
                "insert_row",
                "update_row",
                "delete_row",
                "list_due_items",
                "get_history",
            }
            assert len(payload(await client.call_tool("list_tables", {}))["data"]) == 9
            assert (
                payload(await client.call_tool("describe_table", {"table": "profile"}))["data"][
                    "table"
                ]
                == "profile"
            )
            created = payload(
                await client.call_tool(
                    "insert_row",
                    {
                        "table": "profile",
                        "data": {"name": "Alice", "email": "alice@example.invalid"},
                    },
                )
            )["data"]
            row_id = created["row"]["id"]
            assert created["row"]["email"] == MASK
            assert (
                payload(await client.call_tool("query_rows", {"table": "profile"}))["data"][0][
                    "email"
                ]
                == MASK
            )
            assert (
                payload(
                    await client.call_tool(
                        "update_row",
                        {"table": "profile", "id": row_id, "data": {"city": "Sample City"}},
                    )
                )["data"]["row"]["city"]
                == "Sample City"
            )
            assert (
                payload(await client.call_tool("get_history", {"table": "profile"}))["data"][0][
                    "after"
                ]["email"]
                == MASK
            )
            assert payload(await client.call_tool("list_due_items", {"within": "30d"}))["ok"]
            assert not payload(
                await client.call_tool("delete_row", {"table": "profile", "id": row_id})
            )["ok"]
            assert payload(
                await client.call_tool(
                    "delete_row", {"table": "profile", "id": row_id, "confirm": True}
                )
            )["data"]["deleted"]

    asyncio.run(scenario())


def test_real_mcp_stdio(tmp_path):
    async def scenario():
        options = StdioServerParameters(
            command=sys.executable,
            args=["-m", "personal_data_hub.cli", "--data-dir", str(tmp_path / "stdio"), "mcp"],
            env=dict(os.environ),
        )
        async with stdio_client(options) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=15)
            ) as client:
                assert (await client.initialize()).serverInfo.name == "personal-data-hub"
                assert len(payload(await client.call_tool("list_tables", {}))["data"]) == 9

    asyncio.run(scenario())
