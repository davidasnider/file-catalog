import logging
from typing import Dict, Any

import pandas as pd

from src.core.plugin_registry import AnalyzerBase, register_analyzer
from src.core.analyzer_names import SPREADSHEET_ANALYZER_NAME

logger = logging.getLogger(__name__)

SPREADSHEET_MIMES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "text/csv",
    "application/csv",
    "application/vnd.oasis.opendocument.spreadsheet",  # .ods
}

SPREADSHEET_EXTENSIONS = {".xlsx", ".csv", ".ods"}

MAX_SAMPLE_ROWS = 5
MAX_SPREADSHEET_ROWS = 10000


@register_analyzer(name=SPREADSHEET_ANALYZER_NAME, depends_on=[], version="1.0")
class SpreadsheetAnalyzerPlugin(AnalyzerBase):
    """
    Extracts and summarizes data from spreadsheet files (.xlsx, .csv, .ods).
    Provides column headers, row/column counts, basic stats, and sample data.
    """

    def should_run(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> bool:
        if mime_type in SPREADSHEET_MIMES:
            return True
        return any(file_path.lower().endswith(ext) for ext in SPREADSHEET_EXTENSIONS)

    async def analyze(
        self, file_path: str, mime_type: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info(f"Analyzing spreadsheet {file_path}")

        try:
            sheets = self._read_spreadsheet(file_path, mime_type)

            result = {
                "sheets": sheets,
                "total_sheets": len(sheets),
                "source": "spreadsheet_analyzer",
            }

            return result

        except Exception as e:
            logger.error(f"Failed to analyze spreadsheet {file_path}: {e}")
            raise Exception(f"Spreadsheet analysis failed: {str(e)}")

    def _read_spreadsheet(self, file_path: str, mime_type: str) -> list[Dict[str, Any]]:
        """Read spreadsheet and return per-sheet summaries."""
        lower_path = file_path.lower()
        sheets_data = []

        if lower_path.endswith(".csv") or mime_type in ("text/csv", "application/csv"):
            df = pd.read_csv(file_path, nrows=MAX_SPREADSHEET_ROWS)
            sheets_data.append(self._summarize_dataframe(df, "Sheet1"))
        elif (
            lower_path.endswith(".ods")
            or mime_type == "application/vnd.oasis.opendocument.spreadsheet"
        ):
            all_sheets = pd.read_excel(
                file_path, engine="odf", sheet_name=None, nrows=MAX_SPREADSHEET_ROWS
            )
            for name, df in all_sheets.items():
                sheets_data.append(self._summarize_dataframe(df, str(name)))
        else:
            # .xlsx
            all_sheets = pd.read_excel(
                file_path,
                engine="openpyxl",
                sheet_name=None,
                nrows=MAX_SPREADSHEET_ROWS,
            )
            for name, df in all_sheets.items():
                sheets_data.append(self._summarize_dataframe(df, str(name)))

        return sheets_data

    def _summarize_dataframe(self, df: pd.DataFrame, sheet_name: str) -> Dict[str, Any]:
        """Generate a summary dict for a single DataFrame/sheet."""
        column_names = list(df.columns.astype(str))

        # Basic numeric stats
        numeric_stats = {}
        numeric_df = df.select_dtypes(include="number")
        if not numeric_df.empty:
            desc = numeric_df.describe()
            for col in desc.columns:
                stats: Dict[str, Any] = {}
                for k, v in desc[col].to_dict().items():
                    # Convert NumPy scalar types (e.g., np.float64, np.int64)
                    # to native Python types for JSON serialization
                    if hasattr(v, "item"):
                        try:
                            v = v.item()
                        except Exception:
                            pass
                    if isinstance(v, float):
                        v = round(v, 4)
                    stats[k] = v
                numeric_stats[str(col)] = stats

        # Sample rows (first N rows as list of dicts)
        sample_rows = (
            df.head(MAX_SAMPLE_ROWS).fillna("").astype(str).to_dict(orient="records")
        )

        return {
            "sheet_name": sheet_name,
            "total_rows": len(df),
            "total_columns": len(column_names),
            "column_names": column_names,
            "numeric_stats": numeric_stats,
            "sample_data": sample_rows,
        }
