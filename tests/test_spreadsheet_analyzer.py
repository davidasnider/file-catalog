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
