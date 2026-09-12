## 2024-05-15 - Streamlit Accessibility and Empty States
**Learning:** Adding `help` parameters to Streamlit UI components (like multiselects and columns) acts as accessible tooltips, significantly improving the experience for users unsure about filter functionality. Additionally, replacing generic "No documents found" messages with actionable empty states (e.g., "Try adjusting your criteria in the sidebar") reduces user frustration when filtering yields no results.
**Action:** Always provide `help` tooltips on interactive filters and ensure empty states guide the user on how to resolve the empty condition.

## 2024-06-25 - Streamlit Layout Constraints and State Management
**Learning:** Placing wide dataframes inside `st.sidebar` severely restricts readability and creates a cramped UX. Following constraints to place tables in the main view significantly improves data accessibility. Additionally, providing feedback for actions that trigger a page reload (like clearing cache) requires persisting a flag in `st.session_state` before `st.rerun()`, then checking and clearing it at the top of the script to display an `st.toast()`.
**Action:** Always place dataframes in the main layout and use `st.session_state` for cross-rerun UI feedback.
