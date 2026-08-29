## 2025-02-27 - Dashboard Metrics N+1 Query Optimization
**Learning:** The Streamlit dashboard's `get_global_metrics` function originally made three separate, sequential database queries to calculate total, completed, and failed document counts on every dashboard load or filter action. Because this is executed constantly as users interact with the UI, this "1+1+1" query pattern caused unnecessary database overhead and lock contention.
**Action:** Always look for opportunities to consolidate multiple sequential scalar queries into a single query using conditional aggregation (e.g., `func.sum(case(...))`) to reduce database round-trips and improve responsiveness.

## 2025-02-27 - Replace DB queries for distinct statuses with Enum iteration
**Learning:** The `get_all_statuses` and `get_all_task_statuses` functions in the Streamlit app queried the database for distinct statuses using `SELECT DISTINCT`. These statuses are statically defined in `DocumentStatus` and `TaskStatus` enums. Querying a potentially large table for static enum values is unnecessary overhead.
**Action:** Replace `SELECT DISTINCT` queries on enum columns with direct iteration over the Python Enum values to avoid database queries entirely.
