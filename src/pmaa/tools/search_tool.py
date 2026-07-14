from pmaa.schemas.task import Source


def mock_search(query: str) -> list[Source]:
    return [
        Source(
            title=f"Overview for {query}",
            url="https://langchain-ai.github.io/langgraph/",
            snippet=f"High-level background information about {query}.",
        ),
        Source(
            title=f"Practical guide for {query}",
            url="https://langchain-ai.github.io/langgraph/tutorials/",
            snippet=f"Implementation-oriented notes about {query}.",
        ),
    ]
