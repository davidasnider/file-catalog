import streamlit as st
import asyncio
from sqlmodel import select
import pandas as pd
import json
from src.ui.snippets import render_snippet

from src.db.engine import async_session_maker
from src.db.models import Document, AnalysisTask
from src.db.fts import search_fts
from src.core.analyzer_names import (
    TEXT_EXTRACTOR_NAME,
    SUMMARIZER_NAME,
    DEEP_SUMMARIZER_NAME,
    ESTATE_ANALYZER_NAME,
    VISION_ANALYZER_NAME,
    VIDEO_ANALYZER_NAME,
    PII_HARVESTER_NAME,
    PASSWORD_EXTRACTOR_NAME,
    METADATA_EXTRACTOR_NAME,
)

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
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        border: 1px solid rgba(128,128,128,0.2);
    }
</style>
""",
)


@st.cache_data(ttl=10)
def fetch_documents(selected_statuses: list[str], search_query: str):
    """Fetch filtered documents from the database."""

    async def _fetch():
        async with async_session_maker() as session:
            stmt = select(Document)
            if not selected_statuses:
                # Empty selection means user deselected all — return nothing
                return []
            stmt = stmt.where(Document.status.in_(selected_statuses))
            if search_query:
                escaped_query = (
                    search_query.replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )
                stmt = stmt.where(Document.path.like(f"%{escaped_query}%", escape="\\"))

            stmt = stmt.order_by(Document.id.desc())
            res = await session.execute(stmt)
            return res.scalars().all()

    return asyncio.run(_fetch())


@st.cache_data(ttl=5)
def fetch_document_tasks(doc_id: int):
    """Fetch all tasks for a specific document."""

    async def _fetch():
        async with async_session_maker() as session:
            stmt = select(AnalysisTask).where(AnalysisTask.document_id == doc_id)
            res = await session.execute(stmt)
            return res.scalars().all()

    return asyncio.run(_fetch())


@st.cache_data(ttl=5)
def fetch_all_tasks_for_documents(doc_ids: list[int]):
    """Fetch all tasks for a list of documents in a single query, chunked to prevent SQLite parameter limits."""

    async def _fetch():
        async with async_session_maker() as session:
            tasks = []
            chunk_size = 900
            for i in range(0, len(doc_ids), chunk_size):
                chunk = doc_ids[i : i + chunk_size]
                stmt = select(AnalysisTask).where(AnalysisTask.document_id.in_(chunk))
                res = await session.execute(stmt)
                tasks.extend(res.scalars().all())

            task_dict = {doc_id: [] for doc_id in doc_ids}
            for t in tasks:
                task_dict[t.document_id].append(t)
            return task_dict

    if not doc_ids:
        return {}
    return asyncio.run(_fetch())


@st.cache_data(ttl=5)
def get_global_metrics():
    """Fetch aggregate metrics for the dashboard."""

    async def _fetch():
        from sqlalchemy import func

        async with async_session_maker() as session:
            total = await session.scalar(select(func.count(Document.id)))
            completed = await session.scalar(
                select(func.count(Document.id)).where(Document.status == "COMPLETED")
            )
            failed = await session.scalar(
                select(func.count(Document.id)).where(Document.status == "FAILED")
            )
            return {"total": total, "completed": completed, "failed": failed}

    return asyncio.run(_fetch())


def get_status_color(status_str: str) -> str:
    color_map = {
        "COMPLETED": "🟢",
        "PENDING": "🟡",
        "ANALYZING": "🔵",
        "FAILED": "🔴",
        "IN_PROGRESS": "🔵",
        "RETRIES": "🟠",
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

    # Sidebar Filters
    with st.sidebar:
        st.header("Filters")

        if st.button("🔄 Refresh Cache"):
            st.cache_data.clear()
            st.rerun()

        # Get unique statuses for the multiselect (cached)
        @st.cache_data(ttl=3600)
        def get_all_statuses():
            async def _fetch():
                async with async_session_maker() as session:
                    res = await session.execute(select(Document.status).distinct())
                    return [s.name for s in res.scalars().all()]

            return asyncio.run(_fetch())

        unique_doc_statuses = get_all_statuses()
        selected_doc_statuses = st.multiselect(
            "Filter by Document Status",
            unique_doc_statuses,
            default=unique_doc_statuses,
        )

        search_query = st.text_input("Search path...", "")
        fts_query = st.text_input(
            "Full Text Content Search...",
            "",
            help="Search extracted text, summaries, and transcripts using SQLite FTS5",
        )

        st.divider()
        st.subheader("🔍 Task Status Filter")

        @st.cache_data(ttl=3600)
        def get_all_task_statuses():
            async def _fetch():
                async with async_session_maker() as session:
                    res = await session.execute(select(AnalysisTask.status).distinct())
                    return [s.name for s in res.scalars().all()]

            return asyncio.run(_fetch())

        unique_task_statuses = get_all_task_statuses()
        selected_task_statuses = st.multiselect(
            "Filter by Task Status",
            unique_task_statuses,
            default=unique_task_statuses,
        )

        st.divider()
        st.subheader("💡 Smart Filters")
        smart_filters = st.multiselect(
            "Quick Filters",
            ["Estate Documents", "NSFW Content", "Contains Passwords"],
            default=[],
        )

    # Fetch Filtered Documents
    with st.spinner("Fetching documents..."):
        documents = fetch_documents(selected_doc_statuses, search_query)

    if not documents:
        st.info("No documents found matching your filters.")
        return

    # Apply smart filters and search refinement in-memory on the SQL-filtered subset
    filtered_docs = []

    doc_tasks_map = {}
    needs_task_data = smart_filters or (selected_task_statuses != unique_task_statuses)
    if needs_task_data and documents:
        doc_tasks_map = fetch_all_tasks_for_documents([doc.id for doc in documents])

    for doc in documents:
        # SQL filter handled selected_doc_statuses and search_query,
        # but we might still want to apply smart filters which require task data.
        if smart_filters:
            doc_tasks = doc_tasks_map.get(doc.id, [])
            match_smart = True
            for f in smart_filters:
                if f == "Estate Documents":
                    estate_task = next(
                        (t for t in doc_tasks if t.task_name == ESTATE_ANALYZER_NAME),
                        None,
                    )
                    is_estate = False
                    if estate_task and estate_task.result_data:
                        try:
                            res = json.loads(estate_task.result_data)
                            is_estate = res.get("is_estate_document", False)
                        except Exception:
                            pass
                    if not is_estate:
                        match_smart = False

                elif f == "NSFW Content":
                    nsfw_task = next(
                        (
                            t
                            for t in doc_tasks
                            if t.task_name
                            in [
                                VISION_ANALYZER_NAME,
                                VIDEO_ANALYZER_NAME,
                                "vision_analyzer",
                                "video_analyzer",
                            ]
                        ),
                        None,
                    )
                    is_nsfw = False
                    if nsfw_task and nsfw_task.result_data:
                        try:
                            res = json.loads(nsfw_task.result_data)
                            if "is_sfw" in res:
                                is_nsfw = not res.get("is_sfw", True)
                        except Exception:
                            pass
                    if not is_nsfw:
                        match_smart = False

                elif f == "Contains Passwords":
                    pw_task = next(
                        (
                            t
                            for t in doc_tasks
                            if t.task_name == PASSWORD_EXTRACTOR_NAME
                        ),
                        None,
                    )
                    has_passwords = False
                    if pw_task and pw_task.result_data:
                        try:
                            res = json.loads(pw_task.result_data)
                            if res.get("passwords"):
                                has_passwords = True
                        except Exception:
                            pass
                    if not has_passwords:
                        pii_task = next(
                            (t for t in doc_tasks if t.task_name == PII_HARVESTER_NAME),
                            None,
                        )
                        if pii_task and pii_task.result_data:
                            try:
                                res = json.loads(pii_task.result_data)
                                pii_data = res.get("pii", {})
                                if pii_data.get("passwords") or pii_data.get("secrets"):
                                    has_passwords = True
                            except Exception:
                                pass
                    if not has_passwords:
                        match_smart = False

            if not match_smart:
                continue

        # Task-status filter: skip docs whose tasks don't match selected statuses
        if selected_task_statuses != unique_task_statuses:
            doc_tasks = doc_tasks_map.get(doc.id, [])
            if not doc_tasks:
                continue
            if not any(t.status.name in selected_task_statuses for t in doc_tasks):
                continue

        filtered_docs.append(doc)

    # Perform FTS Search if query is provided
    fts_results = {}
    if fts_query.strip():
        with st.spinner("Searching full text index..."):

            async def run_fts():
                async with async_session_maker() as session:
                    return await search_fts(session, fts_query.strip(), limit=100)

            try:
                results = asyncio.run(run_fts())
                for r in results:
                    fts_results[r["document_id"]] = r

                # Filter our already-filtered docs down to only FTS matches
                filtered_docs = [d for d in filtered_docs if d.id in fts_results]
            except Exception as e:
                st.sidebar.error(f"FTS Search Error: {e}")

    # Render Document Index inside the Sidebar
    with st.sidebar:
        st.divider()
        st.subheader("Document Index")

        selected_row = None
        if filtered_docs:
            table_data = []
            for doc in filtered_docs:
                table_data.append(
                    {
                        "Document Status": f"{get_status_color(doc.status.name)}",  # Simplified
                        "File": doc.path.split("/")[-1],
                        "ID": doc.id,
                    }
                )

            df = pd.DataFrame(table_data)

            # Interactive Dataframe in sidebar
            event = st.dataframe(
                df[["Document Status", "File"]],
                height=400,
                width="stretch",
                hide_index=True,
                column_config={
                    "Document Status": st.column_config.TextColumn(
                        "Status", width="small"
                    ),
                    "File": st.column_config.TextColumn("File", width="large"),
                },
                on_select="rerun",
                selection_mode="single-row",
            )

            if len(event.selection.rows) > 0:
                selected_idx = event.selection.rows[0]
                selected_row = df.iloc[selected_idx]

    # Metrics Row
    metrics = get_global_metrics()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Documents", metrics["total"])
    col2.metric("Filtered", len(filtered_docs))
    col3.metric("Completed", metrics["completed"])
    col4.metric("Failed", metrics["failed"])

    # Detail View Context
    if selected_row is not None:
        doc_id = int(selected_row["ID"])

        # Display FTS Search snippets if applicable
        if fts_results and doc_id in fts_results:
            st.markdown("### 🔍 Search Match")
            match = fts_results[doc_id]

            if match.get("summary_snippet"):
                st.markdown(
                    f"**In Summary:** ...{render_snippet(match['summary_snippet'])}...",
                )
            if match.get("content_snippet"):
                st.markdown(
                    f"**In Content:** ...{render_snippet(match['content_snippet'])}...",
                )
            st.divider()
        selected_doc = next((d for d in filtered_docs if d.id == doc_id), None)

        if selected_doc:
            st.divider()

            st.subheader("Document Details")
            st.markdown(f"**File:** `{selected_doc.path.split('/')[-1]}`")

            # Fetch Tasks for selected document only
            raw_tasks = fetch_document_tasks(doc_id)

            # Separate out the Summarizer
            # Prioritize DeepSummarizer for large documents
            deep_summarizer_task = next(
                (t for t in raw_tasks if t.task_name == DEEP_SUMMARIZER_NAME), None
            )
            standard_summarizer_task = next(
                (t for t in raw_tasks if t.task_name == SUMMARIZER_NAME), None
            )

            summarizer_task = deep_summarizer_task or standard_summarizer_task

            # If DeepSummarizer exists but skipped/failed, try standard one
            if deep_summarizer_task:
                try:
                    ds_data = json.loads(deep_summarizer_task.result_data)
                    if (
                        ds_data.get("skipped")
                        or deep_summarizer_task.status.name == "FAILED"
                    ):
                        summarizer_task = standard_summarizer_task
                except (json.JSONDecodeError, TypeError):
                    summarizer_task = standard_summarizer_task

            main_tasks = [
                t
                for t in raw_tasks
                if t.task_name not in [SUMMARIZER_NAME, DEEP_SUMMARIZER_NAME]
            ]

            # 1. AI Summary Section (Top)
            if (
                summarizer_task
                and summarizer_task.status.name != "FAILED"
                and summarizer_task.result_data
            ):
                try:
                    data = json.loads(summarizer_task.result_data)
                    if not data.get("skipped"):
                        st.subheader("AI Summary")
                        # Use extensive_summary if available (from DeepSummarizer)
                        summary_content = data.get("extensive_summary") or data.get(
                            "summary", ""
                        )
                        st.info(summary_content)
                        st.caption(
                            f"Generated by: {summarizer_task.task_name} ({data.get('model', 'Unknown')})"
                        )
                        st.divider()
                except (json.JSONDecodeError, TypeError):
                    pass
            elif summarizer_task:
                st.subheader("AI Summary")
                if summarizer_task.status.name == "FAILED":
                    st.error(f"Summarization failed: {summarizer_task.error_message}")
                else:
                    st.warning(
                        f"Summarization is in progress or pending (Status: {summarizer_task.status.name})"
                    )
                st.divider()

            # 2. Image Viewer Section (Middle)
            import os

            if selected_doc.mime_type and selected_doc.mime_type.startswith("image/"):
                st.subheader("Image Viewer")
                if os.path.exists(selected_doc.path):
                    st.image(selected_doc.path)
                else:
                    st.warning("Image file not found on disk.")
                st.divider()

            # 3. Extraction Tasks Section (Bottom)
            # Visually sort the tasks so Extractors appear before Analyzers, and skipped tasks go to the bottom
            def task_sort_key(t):
                is_skipped = get_task_status_color(t) == "⚪"
                if t.task_name == METADATA_EXTRACTOR_NAME:
                    order = 0
                elif t.task_name == TEXT_EXTRACTOR_NAME:
                    order = 1
                elif t.task_name == PASSWORD_EXTRACTOR_NAME:
                    order = 2
                elif t.task_name == PII_HARVESTER_NAME:
                    order = 3
                else:
                    order = 4
                return (1 if is_skipped else 0, order, t.task_name)

            tasks = sorted(main_tasks, key=task_sort_key)

            if not tasks:
                st.info("No analysis tasks recorded for this document.")
            else:
                for task in tasks:
                    is_skipped = get_task_status_color(task) == "⚪"
                    with st.expander(
                        f"{get_task_status_color(task)} {task.task_name} (v{task.plugin_version})",
                        expanded=not is_skipped,
                    ):
                        if task.status.name == "FAILED":
                            st.error(f"**Error:** {task.error_message}")
                        elif task.result_data:
                            try:
                                data = json.loads(task.result_data)

                                # Formatted visualizations based on plugin type
                                if task.task_name == "EstateAnalyzer":
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
                                    # Generic raw JSON dump => formatted list
                                    if data.get("skipped"):
                                        st.warning(
                                            f"Skipped: {data.get('reason', 'Unknown reason')}"
                                        )
                                    else:
                                        for k, v in data.items():
                                            if k not in [
                                                "skipped",
                                                "source",
                                                "source_plugin",
                                            ]:
                                                # Robustly format nested dictionaries/arrays or pass native strings
                                                if isinstance(v, (list, dict)):
                                                    val_str = f"```json\n{json.dumps(v, indent=2)}\n```"
                                                    st.markdown(
                                                        f"**{k.replace('_', ' ').title()}**:\n{val_str}"
                                                    )
                                                else:
                                                    st.markdown(
                                                        f"**{k.replace('_', ' ').title()}**: {v}"
                                                    )
                            except json.JSONDecodeError:
                                st.warning("Failed to parse result data.")
                                st.code(task.result_data)
                        else:
                            st.write("No result data available.")

    else:
        st.info("Select a document from the table to view its analysis details.")


if __name__ == "__main__":
    main()
