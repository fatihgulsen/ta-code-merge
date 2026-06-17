from unittest.mock import MagicMock
from es.transform import create_dedup_transform, TRANSFORM_ID


def test_transform_source_is_wildcard():
    es = MagicMock()
    es.indices.exists.return_value = True
    es.transform.get_transform.side_effect = Exception("yok")
    create_dedup_transform(es)
    _, kwargs = es.transform.put_transform.call_args
    src = kwargs["body"]["source"]["index"]
    assert src == ["living_companies_*"]
