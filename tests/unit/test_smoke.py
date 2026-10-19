import minirag


def test_package_exposes_version() -> None:
    assert minirag.__version__ == "0.1.0"
