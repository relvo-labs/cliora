from app.retention import targets


def test_revoked_session_tokens_have_ninety_day_retention() -> None:
    by_table = {target.table: target for target in targets()}

    token_target = by_table["session_tokens"]
    assert token_target.column == "revoked_at"
    assert token_target.days == 90
