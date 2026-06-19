from scripts import bootstrap_metabase
from scripts.bootstrap_metabase import QUESTIONS, ensure_questions, normalize_sql, wait_for_metabase


class FlakyMetabaseClient:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, path: str):
        self.calls += 1
        if self.calls == 1:
            raise ConnectionResetError(54, "Connection reset by peer")
        return {"setup-token": None}


def test_wait_for_metabase_retries_connection_reset(monkeypatch) -> None:
    timestamps = iter([0, 1])
    sleeps: list[int] = []
    monkeypatch.setattr("scripts.bootstrap_metabase.time.monotonic", lambda: next(timestamps, 1))
    monkeypatch.setattr("scripts.bootstrap_metabase.time.sleep", sleeps.append)
    client = FlakyMetabaseClient()

    assert wait_for_metabase(client) is True

    assert client.calls == 2
    assert sleeps == [2]


def test_metabase_questions_include_processing_insights() -> None:
    question_names = {question.name for question in QUESTIONS}

    assert {
        "Active documents by current step",
        "Active documents detail",
        "Step status matrix",
        "Failed documents by failed step",
        "Waiting partner documents by age",
    } <= question_names


def test_metabase_questions_include_snapshot_usage_and_data_quality_insights() -> None:
    question_names = {question.name for question in QUESTIONS}

    assert {
        "Documents by user",
        "Failed documents by organization",
        "Waiting partner by organization",
        "Ready documents without OCR text",
        "Ready documents without metadata",
        "Ready documents without chunks",
        "Metadata doc types",
        "Partner result coverage",
        "Snapshot data inconsistencies",
    } <= question_names


def test_metabase_dashboards_group_questions_by_operational_purpose() -> None:
    dashboard_names = {dashboard.name for dashboard in bootstrap_metabase.DASHBOARDS}
    question_names = {question.name for question in QUESTIONS}

    assert dashboard_names == {
        "Primmo operations snapshot",
        "Primmo problem documents",
        "Primmo usage",
        "Primmo data quality",
    }
    for dashboard in bootstrap_metabase.DASHBOARDS:
        assert dashboard.question_names
        assert set(dashboard.question_names) <= question_names
        assert dashboard.description
        assert dashboard.collection_position > 0


def test_metabase_questions_have_descriptions_for_card_info_tooltips() -> None:
    assert all(question.description for question in QUESTIONS)


def test_metabase_questions_do_not_reference_missing_duration_columns() -> None:
    all_queries = "\n".join(normalize_sql(question.query).lower() for question in QUESTIONS)

    assert "started_at" not in all_queries
    assert "finished_at" not in all_queries


def test_ready_documents_without_chunks_query_guards_jsonb_array_length() -> None:
    question_by_name = {question.name: question for question in QUESTIONS}
    query = " ".join(
        normalize_sql(question_by_name["Ready documents without chunks"].query).lower().split()
    )

    assert "case when jsonb_typeof(e.chunks_json) = 'array'" in query
    assert "then jsonb_array_length(e.chunks_json) = 0" in query


def test_questions_with_template_tags_declare_matching_sql_variables() -> None:
    for question in QUESTIONS:
        query = normalize_sql(question.query)
        for tag_name in question.template_tags:
            assert f"{{{{{tag_name}}}}}" in query


def test_dashboard_parameters_are_declared_and_mapped_to_question_variables() -> None:
    for dashboard in bootstrap_metabase.DASHBOARDS:
        parameter_ids = {parameter["id"] for parameter in bootstrap_metabase.dashboard_parameters(dashboard)}
        assert set(dashboard.parameter_ids) == parameter_ids
        assert parameter_ids

        for question_name in dashboard.question_names:
            question = bootstrap_metabase.question_by_name(question_name)
            mappings = bootstrap_metabase.parameter_mappings_for_question(dashboard, question, card_id=123)
            mapped_parameter_ids = {mapping["parameter_id"] for mapping in mappings}

            assert mapped_parameter_ids <= parameter_ids
            assert mapped_parameter_ids == set(question.template_tags) & parameter_ids


class ExistingCardsClient:
    def __init__(self) -> None:
        self.put_calls: list[tuple[str, dict]] = []
        self.post_calls: list[tuple[str, dict]] = []

    def get(self, path: str):
        assert path == "/api/card"
        return {
            "data": [
                {"id": index + 1, "name": question.name}
                for index, question in enumerate(QUESTIONS)
            ]
        }

    def put(self, path: str, payload: dict):
        self.put_calls.append((path, payload))
        return {"id": int(path.rsplit("/", 1)[1])}

    def post(self, path: str, payload: dict):
        self.post_calls.append((path, payload))
        return {"id": 999}


def test_ensure_questions_updates_existing_cards() -> None:
    client = ExistingCardsClient()

    card_ids_by_name = ensure_questions(client, database_id=42)

    assert card_ids_by_name == {
        question.name: index + 1
        for index, question in enumerate(QUESTIONS)
    }
    assert client.post_calls == []
    assert len(client.put_calls) == len(QUESTIONS)
    first_path, first_payload = client.put_calls[0]
    assert first_path == "/api/card/1"
    assert first_payload["description"]
    assert first_payload["dataset_query"]["database"] == 42
    assert "template-tags" in first_payload["dataset_query"]["native"]


class ExistingDashboardsClient:
    def __init__(self) -> None:
        self.post_calls: list[tuple[str, dict]] = []
        self.put_calls: list[tuple[str, dict]] = []

    def get(self, path: str):
        assert path == "/api/dashboard"
        return {"data": [{"id": 7, "name": "Primmo operations snapshot"}]}

    def post(self, path: str, payload: dict):
        self.post_calls.append((path, payload))
        return {"id": 20 + len(self.post_calls)}

    def put(self, path: str, payload: dict):
        self.put_calls.append((path, payload))


def test_ensure_dashboards_reuses_existing_and_creates_missing_dashboards() -> None:
    client = ExistingDashboardsClient()

    dashboard_ids_by_name = bootstrap_metabase.ensure_dashboards(client)

    assert dashboard_ids_by_name["Primmo operations snapshot"] == 7
    assert set(dashboard_ids_by_name) == {
        "Primmo operations snapshot",
        "Primmo problem documents",
        "Primmo usage",
        "Primmo data quality",
    }
    assert [payload["name"] for _, payload in client.post_calls] == [
        "Primmo problem documents",
        "Primmo usage",
        "Primmo data quality",
    ]
    assert client.put_calls[0] == (
        "/api/dashboard/7",
        {
            "name": "Primmo operations snapshot",
            "description": bootstrap_metabase.DASHBOARDS[0].description,
            "collection_id": None,
            "collection_position": bootstrap_metabase.DASHBOARDS[0].collection_position,
        },
    )
    assert all(payload["collection_id"] is None for _, payload in client.post_calls)
    assert all(payload["collection_position"] for _, payload in client.post_calls)


class DashboardAttachmentClient:
    def __init__(self) -> None:
        self.put_calls: list[tuple[str, dict]] = []

    def put(self, path: str, payload: dict):
        self.put_calls.append((path, payload))


def test_attach_cards_to_dashboards_uses_each_dashboard_question_subset() -> None:
    client = DashboardAttachmentClient()
    dashboard_ids_by_name = {
        dashboard.name: index + 1
        for index, dashboard in enumerate(bootstrap_metabase.DASHBOARDS)
    }
    card_ids_by_name = {
        question.name: index + 101
        for index, question in enumerate(QUESTIONS)
    }

    bootstrap_metabase.attach_cards_to_dashboards(
        client,
        dashboard_ids_by_name,
        card_ids_by_name,
    )

    assert len(client.put_calls) == len(bootstrap_metabase.DASHBOARDS)
    first_path, first_payload = client.put_calls[0]
    first_dashboard = bootstrap_metabase.DASHBOARDS[0]
    assert first_path == f"/api/dashboard/{dashboard_ids_by_name[first_dashboard.name]}"
    assert first_payload["parameters"] == bootstrap_metabase.dashboard_parameters(first_dashboard)
    assert [
        dashcard["card_id"]
        for dashcard in first_payload["dashcards"]
    ] == [
        card_ids_by_name[question_name]
        for question_name in first_dashboard.question_names
    ]
    assert any(dashcard["col"] > 0 for dashcard in first_payload["dashcards"])
    assert all(dashcard["parameter_mappings"] for dashcard in first_payload["dashcards"])
