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


async def fetch_all_data():
    """Fetch all documents and tasks asynchronously to avoid N+1 queries."""
    async with async_session_maker() as session:
        docs = (
            (await session.execute(select(Document).order_by(Document.id.desc())))
            .scalars()
            .all()
        )
        tasks = (await session.execute(select(AnalysisTask))).scalars().all()
        return docs, tasks


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


def get_task_status_color(task: AnalysisTask) -> str:
    status_base = (
        task.status.name.split(".")[-1] if "." in task.status.name else task.status.name
    )

    if status_base == "COMPLETED" and task.result_data:
        try:
            data = json.loads(task.result_data)
            if data.get("skipped"):
                return "⚪"

            # If an extractor explicitly tried but found NO text (and didn't gracefully skip), alert as RED.
            if "extracted" in data and not data.get("extracted"):
                return "🔴"
        except json.JSONDecodeError:
            pass

    return get_status_color(task.status.name)


def main():
    st.title("📂 Local AI File Catalog")
    st.markdown("Analyze and interact with your digitally archived documents.")

    # Fetch data
    with st.spinner("Loading database records..."):
        try:
            documents, all_tasks = asyncio.run(fetch_all_data())
        except Exception as e:
            st.error(f"Failed to connect to database: {e}")
            return

    if not documents:
        st.info("No documents found in the database. Run the scanner CLI first!")
        return

    # Map tasks
    tasks_by_doc = {}
    for t in all_tasks:
        tasks_by_doc.setdefault(t.document_id, []).append(t)

    # Sidebar Filters
    with st.sidebar:
        st.header("Filters")

        all_doc_statuses = [doc.status.name for doc in documents]
        unique_doc_statuses = sorted(list(set(all_doc_statuses)))
        selected_doc_statuses = st.multiselect(
            "Filter by Document Status",
            unique_doc_statuses,
            default=unique_doc_statuses,
        )

        all_task_statuses = [t.status.name for t in all_tasks]
        unique_task_statuses = sorted(list(set(all_task_statuses)))
        selected_task_statuses = st.multiselect(
            "Filter by Task Status", unique_task_statuses, default=unique_task_statuses
        )

        search_query = st.text_input("Search path...", "")

    # Apply filters
    filtered_docs = []
    for doc in documents:
        if doc.status.name not in selected_doc_statuses:
            continue
        if search_query.lower() not in doc.path.lower():
            continue

        doc_tasks = tasks_by_doc.get(doc.id, [])
        if selected_task_statuses != unique_task_statuses:
            if not doc_tasks:
                continue
            if not any(t.status.name in selected_task_statuses for t in doc_tasks):
                continue

        filtered_docs.append(doc)

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
                doc_tasks = tasks_by_doc.get(doc.id, [])
                task_badges = "".join([get_task_status_color(t) for t in doc_tasks])

                table_data.append(
                    {
                        "Document Status": f"{get_status_color(doc.status.name)} {doc.status.name}",
                        "Tasks": task_badges,
                        "File": doc.path.split("/")[-1],
                        "Type": doc.mime_type or "Unknown",
                        "Path": doc.path,
                        "ID": doc.id,
                    }
                )

            df = pd.DataFrame(table_data)

            # Interactive Dataframe
            event = st.dataframe(
                df[["Document Status", "Tasks", "File", "Type", "Path"]],
                use_container_width=True,
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
                raw_tasks = tasks_by_doc.get(doc_id, [])

                # Visually sort the tasks so Extractors appear before Analyzers
                def task_sort_key(t):
                    if t.task_name == "MetadataExtractor":
                        return 0
                    if t.task_name == "TextExtractor":
                        return 1
                    if t.task_name == "Summarizer":
                        return 2
                    return 3

                tasks = sorted(raw_tasks, key=task_sort_key)

                if not tasks:
                    st.info("No analysis tasks recorded for this document.")
                else:
                    for task in tasks:
                        with st.expander(
                            f"{get_task_status_color(task)} {task.task_name} (v{task.plugin_version})",
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
