from hansard.evaluation.run import RunOptions, build_parser


def parsed(argv):
    arguments = build_parser().parse_args(argv)
    return RunOptions(
        data_dir=arguments.data_dir,
        output=arguments.output or arguments.benchmark,
        threads=arguments.threads,
        language=arguments.language,
        roster=arguments.roster,
    )


def test_a_run_is_roster_free_unless_asked():
    assert parsed(["ami"]).roster is False


def test_the_roster_flag_reaches_the_options():
    assert parsed(["ami", "--roster"]).roster is True


def test_the_summ_re_benchmark_accepts_the_same_flag():
    assert parsed(["summ-re", "--roster"]).roster is True


def test_the_language_filter_and_the_roster_flag_compose():
    options = parsed(["meetings", "--language", "fr", "--roster"])
    assert options.language == "fr"
    assert options.roster is True
