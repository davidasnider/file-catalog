## 2024-05-27 - [Title]
**Vulnerability:** SQL injection risks due to f-strings with `.like()`
**Learning:** Found several places using `.like(f"%{user_input}%")` in SQLModel queries without escaping or parameterization. This pattern is vulnerable to SQL injection and can also be flagged by static analysis tools. Memory instructions recommend using `.contains(search_query, autoescape=True)` for substring searches to ensure proper parameterization, handle automatic wildcard escaping, and prevent SQL injection.
**Prevention:** Always use `.contains(user_input, autoescape=True)` instead of `.like(f"%{user_input}%")` for substring search in SQLAlchemy/SQLModel.
