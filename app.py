import streamlit as st
import asyncio
from sqlmodel import select
import pandas as pd
import json

from src.db.engine import async_session_maker
from src.db.models import Document, AnalysisTask

# Configure page
st.set_page_config(
    page_title="File Catalog Dashboard",
    page_icon="📂",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for modern styling
st.markdown(
    """
<style>
    .reportview-container {
        background: #f0f2f6;
    }
    .main .block-container {
        padding-top: 2rem;
    }
    .stDataFrame {
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    h1 {
        font-family: 'Inter', sans-serif;
        color: #1e293b;
        font-weight: 700;
    }
    .stMetric {
        background-color: white;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
</style>
""",
    unsafe_allow_html=True,
)


async def fetch_documents():
    """Fetch all documents from the database asynchronously."""
    async with async_session_maker() as session:
        result = await session.execute(select(Document))
        docs = result.scalars().all()
        return docs


async def fetch_tasks_for_doc(document_id: int):
    """Fetch tasks for a specific document."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(AnalysisTask).where(AnalysisTask.document_id == document_id)
        )
        return result.scalars().all()


def get_status_color(status_str: str) -> str:
    color_map = {
        "COMPLETED": "🟢",
        "PENDING": "🟡",
        "ANALYZING": "🔵",
        "FAILED": "🔴",
    }
    # Handling enum string output
    status_base = status_str.split(".")[-1] if "." in status_str else status_str
    return color_map.get(status_base, "⚪")


def main():
    st.title("📂 Local AI File Catalog")
    st.markdown("Analyze and interact with your digitally archived documents.")

    # Fetch data
    with st.spinner("Loading documents from database..."):
        try:
            documents = asyncio.run(fetch_documents())
        except Exception as e:
            st.error(f"Failed to connect to database: {e}")
            return

    if not documents:
        st.info("No documents found in the database. Run the scanner CLI first!")
        return

    # Sidebar Filters
    with st.sidebar:
        st.header("Filters")

        all_statuses = [doc.status.name for doc in documents]
        unique_statuses = sorted(list(set(all_statuses)))
        selected_statuses = st.multiselect(
            "Filter by Status", unique_statuses, default=unique_statuses
        )

        search_query = st.text_input("Search path...", "")

    # Apply filters
    filtered_docs = [
        doc
        for doc in documents
        if doc.status.name in selected_statuses
        and search_query.lower() in doc.path.lower()
    ]

    # Metrics Row
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Documents", len(documents))
    col2.metric("Filtered", len(filtered_docs))
    col3.metric("Completed", sum(1 for d in documents if d.status.name == "COMPLETED"))
    col4.metric("Failed", sum(1 for d in documents if d.status.name == "FAILED"))

    st.divider()

    # Main layout - Left column for table, right for details
    left_col, right_col = st.columns([1.5, 1])

    with left_col:
        st.subheader("Document Index")

        if filtered_docs:
            # Prepare data for dataframe
            table_data = []
            for doc in filtered_docs:
                table_data.append(
                    {
                        "Status": f"{get_status_color(doc.status.name)} {doc.status.name}",
                        "File": doc.path.split("/")[-1],
                        "Path": doc.path,
                        "Type": doc.mime_type or "Unknown",
                        "ID": doc.id,
                    }
                )

            df = pd.DataFrame(table_data)

            # Interactive Dataframe
            event = st.dataframe(
                df[["Status", "File", "Type", "Path"]],
                width="stretch",
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
            )

            # Check if a row was selected
            selected_row = None
            if len(event.selection.rows) > 0:
                selected_idx = event.selection.rows[0]
                selected_row = df.iloc[selected_idx]

    # Detail View Context
    with right_col:
        if selected_row is not None:
            doc_id = int(selected_row["ID"])
            selected_doc = next((d for d in filtered_docs if d.id == doc_id), None)

            if selected_doc:
                st.subheader("Document Details")
                st.markdown(f"**File:** `{selected_doc.path.split('/')[-1]}`")

                # Fetch Tasks
                tasks = asyncio.run(fetch_tasks_for_doc(doc_id))

                if not tasks:
                    st.info("No analysis tasks recorded for this document.")
                else:
                    for task in tasks:
                        with st.expander(
                            f"{get_status_color(task.status.name)} {task.task_name} (v{task.plugin_version})",
                            expanded=True,
                        ):
                            if task.status.name == "FAILED":
                                st.error(f"**Error:** {task.error_message}")
                            elif task.result_data:
                                try:
                                    data = json.loads(task.result_data)

                                    # Formatted visualizations based on plugin type
                                    if task.task_name == "Summarizer":
                                        if data.get("skipped"):
                                            st.warning(
                                                f"Skipped: {data.get('error', 'Unknown reason')}"
                                            )
                                        else:
                                            st.info(data.get("summary", ""))
                                            st.caption(
                                                f"Model: {data.get('model', 'Unknown')}"
                                            )

                                    elif task.task_name == "EstateAnalyzer":
                                        if data.get("skipped"):
                                            st.warning(
                                                f"Skipped: {data.get('error', 'Unknown reason')}"
                                            )
                                        else:
                                            is_estate = data.get(
                                                "is_estate_document", False
                                            )
                                            if is_estate:
                                                st.success(
                                                    "Relevant to Estate/Financial Planning ✅"
                                                )
                                            else:
                                                st.markdown(
                                                    "Not relevant to Estate Planning ❌"
                                                )
                                            st.write(
                                                data.get(
                                                    "reasoning",
                                                    "No reasoning provided.",
                                                )
                                            )

                                    elif (
                                        task.task_name == "TextExtractor"
                                        or task.task_name == "OCRExtractor"
                                    ):
                                        text = data.get("text", "")
                                        if text:
                                            # Using text area to contain large text blocks
                                            st.text_area(
                                                "Extracted Text",
                                                text,
                                                height=150,
                                                disabled=True,
                                            )
                                        else:
                                            st.write("No text extracted.")

                                    else:
                                        # Generic raw JSON dump
                                        st.json(data)

                                except json.JSONDecodeError:
                                    st.warning("Failed to parse result data.")
                                    st.code(task.result_data)
                            else:
                                st.write("No result data available.")
        else:
            st.info("Select a document from the table to view its analysis details.")


if __name__ == "__main__":
    main()
