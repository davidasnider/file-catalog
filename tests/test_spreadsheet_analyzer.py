import pytest
from src.plugins.spreadsheet_analyzer import SpreadsheetAnalyzerPlugin


@pytest.mark.asyncio
async def test_spreadsheet_analyzer_csv(tmp_path):
    plugin = SpreadsheetAnalyzerPlugin()

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("name,age,score\nAlice,30,95.5\nBob,25,87.3\nCharlie,35,91.0\n")

    result = await plugin.analyze(str(csv_file), "text/csv", {})

    assert result["source"] == "spreadsheet_analyzer"
    assert result["total_sheets"] == 1

    sheet = result["sheets"][0]
    assert sheet["sheet_name"] == "Sheet1"
    assert sheet["total_rows"] == 3
    assert sheet["total_columns"] == 3
    assert sheet["column_names"] == ["name", "age", "score"]
    assert len(sheet["sample_data"]) == 3
    assert "age" in sheet["numeric_stats"]


@pytest.mark.asyncio
async def test_spreadsheet_analyzer_xlsx(tmp_path):
    import openpyxl

    plugin = SpreadsheetAnalyzerPlugin()

    xlsx_file = tmp_path / "test.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "People"
    ws.append(["Name", "City", "Value"])
    ws.append(["Alice", "NYC", 100])
    ws.append(["Bob", "LA", 200])
    wb.save(str(xlsx_file))

    result = await plugin.analyze(
        str(xlsx_file),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        {},
    )

    assert result["total_sheets"] == 1
    sheet = result["sheets"][0]
    assert sheet["sheet_name"] == "People"
    assert sheet["total_rows"] == 2
    assert "Name" in sheet["column_names"]
    assert "Value" in sheet["numeric_stats"]


@pytest.mark.asyncio
async def test_spreadsheet_analyzer_ods(tmp_path):
    import pandas as pd
    from unittest.mock import patch

    plugin = SpreadsheetAnalyzerPlugin()

    ods_file = tmp_path / "test.ods"
    ods_file.write_text("fake ods content")

    # Create a dummy DataFrame to return from mock
    df = pd.DataFrame(
        {
            "Name": ["Alice", "Bob"],
            "City": ["NYC", "LA"],
            "Value": [100, 200],
        }
    )

    with patch("pandas.read_excel", return_value={"Sheet1": df}) as mock_read_excel:
        result = await plugin.analyze(
            str(ods_file),
            "application/vnd.oasis.opendocument.spreadsheet",
            {},
        )

        mock_read_excel.assert_called_once()
        _, kwargs = mock_read_excel.call_args
        assert kwargs.get("engine") == "odf"

        assert result["total_sheets"] == 1
        sheet = result["sheets"][0]
        assert sheet["sheet_name"] == "Sheet1"
        assert sheet["total_rows"] == 2
        assert "Name" in sheet["column_names"]
        assert "Value" in sheet["numeric_stats"]


@pytest.mark.asyncio
async def test_spreadsheet_analyzer_should_run():
    plugin = SpreadsheetAnalyzerPlugin()

    assert plugin.should_run("/data.csv", "text/csv", {})
    assert plugin.should_run(
        "/data.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        {},
    )
    assert plugin.should_run(
        "/data.ods",
        "application/vnd.oasis.opendocument.spreadsheet",
        {},
    )

    # Should not run on non-spreadsheet types
    assert not plugin.should_run("/doc.pdf", "application/pdf", {})
    assert not plugin.should_run("/image.jpg", "image/jpeg", {})


@pytest.mark.asyncio
async def test_spreadsheet_analyzer_extension_fallback():
    plugin = SpreadsheetAnalyzerPlugin()

    # Should match by extension even with generic MIME type
    assert plugin.should_run("/data.csv", "application/octet-stream", {})
    assert plugin.should_run("/data.xlsx", "application/octet-stream", {})


@pytest.mark.asyncio
async def test_spreadsheet_analyzer_empty_csv(tmp_path):
    plugin = SpreadsheetAnalyzerPlugin()

    csv_file = tmp_path / "empty.csv"
    csv_file.write_text("col_a,col_b\n")

    result = await plugin.analyze(str(csv_file), "text/csv", {})

    sheet = result["sheets"][0]
    assert sheet["total_rows"] == 0
    assert sheet["column_names"] == ["col_a", "col_b"]


@pytest.mark.asyncio
async def test_spreadsheet_analyzer_json_serialization(tmp_path):
    import json
    import pandas as pd
    from src.plugins.spreadsheet_analyzer import SpreadsheetAnalyzerPlugin

    plugin = SpreadsheetAnalyzerPlugin()
    csv_file = tmp_path / "serializable.csv"

    # Create DataFrame with types that typically cause serialization issues (e.g., numpy scalar types)
    df = pd.DataFrame({"integer_col": [1, 2, 3], "float_col": [1.1, 2.2, 3.3]})
    df.to_csv(csv_file, index=False)

    result = await plugin.analyze(str(csv_file), "text/csv", {})

    # If the serialization fails, json.dumps will raise a TypeError
    serialized_result = json.dumps(result)
    assert isinstance(serialized_result, str)
    assert "integer_col" in serialized_result
