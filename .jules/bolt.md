## 2025-02-27 - Dashboard Metrics N+1 Query Optimization
**Learning:** The Streamlit dashboard's `get_global_metrics` function originally made three separate, sequential database queries to calculate total, completed, and failed document counts on every dashboard load or filter action. Because this is executed constantly as users interact with the UI, this "1+1+1" query pattern caused unnecessary database overhead and lock contention.
**Action:** Always look for opportunities to consolidate multiple sequential scalar queries into a single query using conditional aggregation (e.g., `func.sum(case(...))`) to reduce database round-trips and improve responsiveness.

## 2025-02-27 - Replace DB queries for distinct statuses with Enum iteration
**Learning:** The `get_all_statuses` and `get_all_task_statuses` functions in the Streamlit app queried the database for distinct statuses using `SELECT DISTINCT`. These statuses are statically defined in `DocumentStatus` and `TaskStatus` enums. Querying a potentially large table for static enum values is unnecessary overhead.
**Action:** Replace `SELECT DISTINCT` queries on enum columns with direct iteration over the Python Enum values to avoid database queries entirely.
##

## 2023-10-27 - Batch Fetching to Resolve N+1 Queries
**Learning:** In script utilities like `evaluate_summaries.py`, fetching related data (like `Document` and `AnalysisTask`) inside a loop for each item (N+1 query problem) can cause significant performance bottlenecks, especially since the `session.execute` round trips are asynchronous and add overhead.
**Action:** When fetching related data for a known list of IDs, use a single batch fetch with `Column.in_(ids)` and construct a Python dictionary (e.g., `defaultdict`) to map the results back to the original entities. This replaces O(N) queries with O(1) queries.
