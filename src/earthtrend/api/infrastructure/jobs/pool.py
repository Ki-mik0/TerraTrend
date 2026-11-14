"""Heavy step that a spawned process can import without the database."""


def execute_heavy(case_id: str) -> str:
    if not case_id:
        raise ValueError("empty case")
    return case_id
