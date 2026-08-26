from smoke import parse_args


def test_parse_args_defaults_project():
    pdf, video, project_id = parse_args(
        ["assets/script.pdf", "assets/clips/A001_C0001.mp4"]
    )
    assert pdf.name == "script.pdf"
    assert video.name == "A001_C0001.mp4"
    assert project_id == "notld_1968"


def test_parse_args_accepts_project_flag():
    _, _, project_id = parse_args(
        ["a.pdf", "b.mp4", "--project", "my-film"]
    )
    assert project_id == "my-film"


def test_parse_args_rejects_bad_usage():
    assert parse_args(["only-one"]) is None
    assert parse_args(["a.pdf", "b.mp4", "--project"]) is None
