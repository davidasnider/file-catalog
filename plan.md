1. **Update README.md for Vision Utility and UI Tooltips:**
   - Use `run_in_bash_session` to execute a python script that will read `README.md` and perform string replacement:
     - Replace `Implements proactive image resizing (configurable via \`VISION_MAX_PIXELS\`) to prevent out-of-memory (OOM) crashes during local inference of high-resolution scans.`
       with `Implements proactive image resizing (configurable via \`VISION_MAX_PIXELS\`) to prevent out-of-memory (OOM) crashes during local inference of high-resolution scans. This logic is centralized in the \`src/llm/vision_utils.py\` utility module.`
     - Replace `  - **Accessible Metrics**: Summary metrics feature descriptive tooltips (via \`help\`) for clear context.`
       with `  - **Accessible Metrics & UI**: Summary metrics, interactive filters, and dataframe columns feature descriptive tooltips (via \`help\`) for clear context. Empty states throughout the application provide actionable guidance.`
   - Run `uv run ruff format --preview README.md` to format the file.

2. **Update AGENTS.md for UI Tooltips:**
   - Use `run_in_bash_session` to execute a python script that will read `AGENTS.md` and perform string replacement:
     - Replace `- **Streamlit UI Tooltips**: Utilize \`help='...'\` parameters on \`st.metric\` components to provide accessible tooltips. Do not use \`border=True\` on \`st.metric\` as it is unsupported by the project's Streamlit version and will cause component errors and CI failures.`
       with `- **Streamlit UI Tooltips & Empty States**: Utilize \`help='...'\` parameters on interactive components like \`st.metric\`, \`st.multiselect\`, and dataframe columns to provide accessible tooltips. Do not use \`border=True\` on \`st.metric\` as it is unsupported by the project's Streamlit version and will cause component errors and CI failures. When implementing empty states, provide actionable guidance rather than generic messages.`
   - Run `uv run ruff format --preview AGENTS.md` to format the file.

3. **Complete pre-commit steps:**
   - Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.

4. **Submit the changes:**
   - Use the `submit` tool to push the changes and create a Pull Request on the current branch.

5. **Review Cycle 1 - Request Review:**
   - Use `request_code_review` to request a review.

6. **Review Cycle 1 - Check Feedback:**
   - Use `read_pr_comments` to check for feedback. If there is feedback, the plan will be dynamically updated to address it.

7. **Final Test Execution:**
   - Run `uv run pytest` to ensure changes are correct and regressions have not been introduced.
